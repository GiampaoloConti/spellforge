"""The Balancer: an adversarial reviewer of spell and monster specs.

It assumes the player will exploit every loophole. It sees only the spec and the game's
power references (never the player's raw wording), so a persuasive idea can't talk it into
approving something broken. It approves, adjusts numbers while keeping the fantasy, or
rejects.
"""

from __future__ import annotations

import json

import anthropic

from spellforge.agents.budget import budget_text
from spellforge.agents.llm import AgentConfig, AgentError, ProgressNote, Usage, validated_call
from spellforge.agents.prompts import capabilities, game_facts
from spellforge.agents.specs import Change, MonsterReview, MonsterSpec, SpellReview, SpellSpec
from spellforge.engine.game import PLAYER_MAX_MANA

SPELL_BUDGET = f"""\
- Mana cost is 1-{PLAYER_MAX_MANA}. Mana regenerates 1 per turn, so a cooldown-0 spell can \
be cast about once every `mana_cost` turns in a long fight.
{budget_text()}
- Single-target direct damage should stay near 2 x mana_cost (Firebolt: 3 mana, 5 damage).
- Turn-skipping control: at most 3 turns on one target; at most 2 turns in an area, with \
cooldown at least 4.
- Summons: at most 2 per cast, attack at most 3, lasting at most 8 turns (a status that \
removes them on expiry) or with cooldown at least 6.
- Nothing kills outright or scales with max HP (no percentages)."""

SPELL_EXPLOITS = """\
- Re-casting to stack durations or effects. Chain reactions that never end (effects that \
trigger themselves). Area effects that also hit the caster or allies (fine only if intended).
- Cheap spam: low cost and no cooldown with strong effects.
- Permanent control: turn-skipping that can be refreshed before it ends.
- Summons that never expire or multiply.
- Numbers far above the built-in spells for the same mana.
- Combos with the player's other spells: strong healing plus strong area damage lets the \
player win every fight without risk. If the player already has healing, keep new healing \
small or expensive; if they already have area damage, keep new area damage small."""

MONSTER_BUDGET = """\
Budget for a monster first appearing at depth D:
- max_hp at most 6 + 4 x D (and at most 40); attack at most 2 + D // 2 (and at most 6).
- Ranged or special damage per turn at most its attack.
- Healing others at most 3 per turn; healing itself at most 2 per turn.
- It must be beatable with basic tools (melee, Firebolt, Frost Nova): no immunities, no \
full damage negation, no unavoidable damage above its attack, no instant kills, no \
unlimited spawning (at most 2 spawns in its lifetime).
- A counter should punish a habit, not make that habit useless."""


def monster_budget(depth: int) -> tuple[int, int]:
    """(max_hp, attack) limits for a monster first appearing at `depth`."""
    return min(40, 6 + 4 * depth), min(6, 2 + depth // 2)


def enforce_monster_budget(review: MonsterReview, depth: int) -> MonsterReview:
    """Clamp stats the Balancer let through above budget; an LLM reviewer can be talked round."""
    hp_limit, attack_limit = monster_budget(depth)
    spec = review.spec
    changes = list(review.changes)
    updates: dict[str, int] = {}
    if spec.max_hp > hp_limit:
        updates["max_hp"] = hp_limit
        changes.append(
            Change(
                field="max_hp",
                before=str(spec.max_hp),
                after=str(hp_limit),
                reason=f"budget guard: depth {depth} allows at most {hp_limit} HP",
            )
        )
    if spec.attack > attack_limit:
        updates["attack"] = attack_limit
        changes.append(
            Change(
                field="attack",
                before=str(spec.attack),
                after=str(attack_limit),
                reason=f"budget guard: depth {depth} allows at most {attack_limit} attack",
            )
        )
    if not updates or review.verdict == "reject":
        return review
    return review.model_copy(
        update={
            "verdict": "adjust",
            "changes": changes,
            "spec": spec.model_copy(update=updates),
        }
    )


def spell_system_prompt() -> str:
    return f"""\
You are the Balancer in Spellforge's spell forge. A Designer turned a player's idea into a \
spell spec; you review it before a Coder implements it. You are adversarial: assume the \
player will exploit every loophole in the spec.

# Your job
- Check every number against the budget below and look for exploits.
- verdict "approve": the spec is within budget and has no exploit. Return it unchanged.
- verdict "adjust": fix the numbers (or add a cooldown, shorten a duration, cap targets) so \
it fits the budget, keeping the fantasy intact. Change as little as possible and list every \
change with its reason. Keep the effect summaries and description consistent with the new \
numbers.
- verdict "reject": only when the core of the idea cannot be made fair at any number (for \
example "kill every enemy on the map"). Explain why for the player.
- `rationale` is shown to the player: one or two plain sentences.

# Budget
{SPELL_BUDGET}

# Exploits to look for
{SPELL_EXPLOITS}

# Game facts
{game_facts()}

# What plugins can do
{capabilities()}"""


def monster_system_prompt() -> str:
    return f"""\
You are the Balancer in Spellforge. The Dungeon Master designed a new monster to counter the \
player's play style; you review it before a Coder implements it. Protect the player from \
unfair monsters, and the game from boring ones.

# Your job
- verdict "approve": within budget and fair. Return it unchanged.
- verdict "adjust": fix numbers or behaviour so it fits the budget, keeping its identity \
and its counter. List every change with its reason.
- verdict "reject": only if it cannot be made fair.
- `rationale` is shown to the player: one or two plain sentences.

# Budget
{MONSTER_BUDGET}

# Game facts
{game_facts()}

# What plugins can do
{capabilities()}"""


class Balancer:
    role = "Balancer"

    def __init__(self, client: anthropic.AsyncAnthropic, config: AgentConfig | None = None) -> None:
        self.client = client
        self.config = config or AgentConfig.for_role("balancer")

    async def review_spell(
        self,
        spec: SpellSpec,
        known_spells: list[str],
        on_progress: ProgressNote | None = None,
        measurements: list[str] | None = None,
    ) -> tuple[SpellReview, Usage]:
        """Review a spec. With `measurements` (from the balance probe), the spec was already
        implemented and measured over budget: the Balancer must adjust it."""
        known = "\n".join(f"- {line}" for line in known_spells) or "- (none)"
        prompt = f"""\
Spell spec to review:
```json
{spec.model_dump_json(indent=2)}
```

The player already has these spells (consider combos):
{known}"""
        if measurements:
            listed = "\n".join(f"- {m}" for m in measurements)
            prompt += f"""

This spec was implemented and cast in the balance arena, and it measured OVER BUDGET:
{listed}

Adjust the spec (verdict "adjust") so it fits the limits, keeping the fantasy, or reject it."""
        review, reply = await validated_call(
            self.client,
            self.config,
            system=spell_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
            model=SpellReview,
            role=self.role,
            on_progress=on_progress,
        )
        if review.verdict == "approve":
            if measurements:
                raise AgentError("the Balancer could not bring the spell within budget")
            review = review.model_copy(update={"spec": spec, "changes": []})
        return review, reply.usage

    async def review_monster(
        self,
        spec: MonsterSpec,
        depth: int,
        on_progress: ProgressNote | None = None,
    ) -> tuple[MonsterReview, Usage]:
        prompt = f"""\
Monster spec to review. It will first appear at depth {depth}.
```json
{json.dumps(spec.model_dump(), indent=2)}
```"""
        review, reply = await validated_call(
            self.client,
            self.config,
            system=monster_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
            model=MonsterReview,
            role=self.role,
            on_progress=on_progress,
        )
        if review.verdict == "approve":
            review = review.model_copy(update={"spec": spec, "changes": []})
        return enforce_monster_budget(review, depth), reply.usage
