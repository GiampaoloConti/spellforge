"""The Balancer: an adversarial reviewer of spell and monster specs.

It assumes the player will exploit every loophole. It sees only the spec and the game's
power references (never the player's raw wording), so a persuasive idea can't talk it into
approving something broken. It approves, adjusts numbers while keeping the fantasy, or
rejects.
"""

from __future__ import annotations

import json

import anthropic

from spellforge.agents.llm import AgentConfig, ProgressNote, Usage, validated_call
from spellforge.agents.prompts import capabilities, game_facts
from spellforge.agents.specs import MonsterReview, MonsterSpec, SpellReview, SpellSpec
from spellforge.engine.game import PLAYER_MAX_MANA

SPELL_BUDGET = f"""\
- Mana cost is 1-{PLAYER_MAX_MANA}. Mana regenerates 1 per turn, so a cooldown-0 spell can \
be cast about once every `mana_cost` turns in a long fight.
- Direct damage, single target: at most 2 x mana_cost per cast (Firebolt: 3 mana, 5 damage). \
Add up to +1 damage per 2 turns of cooldown.
- Area damage: at most 1 x mana_cost per creature hit, radius at most 2 unless the cooldown \
is 5 or more.
- Damage over time counts in full (amount x duration) towards the same limits.
- Turn-skipping control (stun, freeze, sleep, polymorph, petrify): at most 3 turns on one \
target; at most 2 turns in an area, and then cooldown at least 4.
- Healing: at most 1.5 x mana_cost per cast, including over time.
- Summons: allies with HP at most 4 + 2 x mana_cost, attack at most 3, at most 2 per cast, \
lasting at most 8 turns (use a status that kills the summon on expiry) or with cooldown at \
least 6.
- Nothing kills outright, ignores the rules above through a percentage, or lasts forever \
without a real cost."""

SPELL_EXPLOITS = """\
- Re-casting to stack durations or effects. Chain reactions that never end (effects that \
trigger themselves). Area effects that also hit the caster or allies (fine only if intended).
- Cheap spam: low cost and no cooldown with strong effects.
- Permanent control: turn-skipping that can be refreshed before it ends.
- Summons that never expire or multiply.
- Numbers far above the built-in spells for the same mana."""

MONSTER_BUDGET = """\
Budget for a monster first appearing at depth D:
- max_hp at most 6 + 4 x D (and at most 40); attack at most 2 + D // 2 (and at most 6).
- Ranged or special damage per turn at most its attack.
- Healing others at most 3 per turn; healing itself at most 2 per turn.
- It must be beatable with basic tools (melee, Firebolt, Frost Nova): no immunities, no \
full damage negation, no unavoidable damage above its attack, no instant kills, no \
unlimited spawning (at most 2 spawns in its lifetime).
- A counter should punish a habit, not make that habit useless."""


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
    ) -> tuple[SpellReview, Usage]:
        known = "\n".join(f"- {line}" for line in known_spells) or "- (none)"
        prompt = f"""\
Spell spec to review:
```json
{spec.model_dump_json(indent=2)}
```

The player already has these spells (consider combos):
{known}"""
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
        return review, reply.usage
