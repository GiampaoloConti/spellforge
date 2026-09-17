"""The Dungeon Master: watches how the player fights and designs monsters to counter it.

    history ─► profile ─► Dungeon Master ─► monster spec ─┬─► Balancer ─► Coder ─┐
                                                          └─► Artist ─────────────┴─► Tester

The profile is computed from engine events (deterministic, no LLM). The Dungeon Master turns it
into a `MonsterSpec` aimed at the player's dominant habit, and the monster goes through the same
Balancer, Coder and Tester as forged spells before it joins deeper levels.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import anthropic

from spellforge.agents.artist import Artist
from spellforge.agents.balancer import Balancer
from spellforge.agents.coder import Coder, monster_task
from spellforge.agents.forge import ProgressCallback, _no_progress
from spellforge.agents.llm import AgentConfig, AgentError, ProgressNote, Usage, validated_call
from spellforge.agents.prompts import capabilities, game_facts
from spellforge.agents.specs import MonsterSpec
from spellforge.agents.spell_writer import Attempt, SpellDraft
from spellforge.agents.tester import Tester
from spellforge.agents.verify import Verification
from spellforge.engine import EventType, Game

DEFAULT_MAX_CODE_ATTEMPTS = 2


# ---- the player profile ----------------------------------------------------------------


def profile_player(game: Game, names: dict[int, str]) -> str:
    """A plain-text summary of how the player has been fighting, from the event history."""
    player = game.player.id
    casts: Counter[str] = Counter()
    melee_attacks = 0
    spell_damage = melee_damage = 0
    kills = 0
    enemy_statuses: Counter[str] = Counter()
    allies = 0
    damage_taken: Counter[str] = Counter()
    hits_per_cast: list[int] = []
    last_action = ""

    for event in game.history:
        data = event.data
        match event.type:
            case EventType.SPELL_CAST if data["caster"] == player:
                casts[data["spell"]] += 1
                hits_per_cast.append(0)
                last_action = "spell"
            case EventType.ATTACKED if data["attacker"] == player:
                melee_attacks += 1
                last_action = "melee"
            case EventType.DAMAGED if data["source"] == player and data["target"] != player:
                if last_action == "melee":
                    melee_damage += data["amount"]
                else:
                    spell_damage += data["amount"]
                    if hits_per_cast:
                        hits_per_cast[-1] += 1
            case EventType.DAMAGED if data["target"] == player and data["source"] not in (
                None,
                player,
            ):
                damage_taken[names.get(data["source"], "something")] += data["amount"]
            case EventType.DIED if data["entity"] != player:
                kills += 1
            case EventType.STATUS_APPLIED if data["entity"] != player and not data["refreshed"]:
                enemy_statuses[data["status"]] += 1
            case EventType.SPAWNED if data["faction"] == "player":
                allies += 1
            case EventType.MOVED if data["entity"] == player:
                last_action = "move"

    spells = game.registry.spells
    cast_lines = [
        f"{spells[spell_id].name} x{count} ({spells[spell_id].description})"
        if spell_id in spells
        else f"{spell_id} x{count}"
        for spell_id, count in casts.most_common()
    ]
    area_casts = sum(1 for hits in hits_per_cast if hits >= 2)
    return "\n".join(
        [
            f"- Reached depth {game.depth} on turn {game.turn}; HP {game.player.hp}/"
            f"{game.player.max_hp}; {kills} kills.",
            f"- Spells cast: {', '.join(cast_lines) or 'none'}.",
            f"- Area hits: {area_casts} of {len(hits_per_cast)} casts damaged 2+ creatures.",
            f"- Melee attacks: {melee_attacks}. Damage dealt: {spell_damage} with spells, "
            f"{melee_damage} in melee.",
            f"- Statuses inflicted on monsters: "
            f"{', '.join(f'{s} x{n}' for s, n in enemy_statuses.most_common()) or 'none'}.",
            f"- Allies summoned: {allies}.",
            f"- Damage taken from: "
            f"{', '.join(f'{k} {n}' for k, n in damage_taken.most_common()) or 'nothing yet'}.",
        ]
    )


# ---- the Dungeon Master agent ------------------------------------------------------------


def system_prompt() -> str:
    return f"""\
You are the Dungeon Master of Spellforge, an endless roguelike where the player invents their \
own spells. You watch how the player fights and design a new monster that counters their \
favourite tactic, so the game keeps asking for new ideas.

# How to design a counter
- Find the player's dominant habit in the profile (a spell they spam, melee rushing, area \
attacks, freezing everything, hiding behind summons...).
- Design one monster that punishes that habit in a readable, fair way, and name the habit \
in `counters`. Good counters make the player change tactics; they never make the player \
helpless. Always give it a clear `weakness`.
- Counter ideas that fit the engine: a ward status that heals back part of the damage taken \
from range (punishes spell spam), thorns that hurt melee attackers, spreading out and \
approaching from several sides (punishes area spells), shaking off turn-skipping statuses \
on its own turn now and then (punishes control), hunting summons first, keeping distance \
and shooting (punishes melee), splitting or calling help when hurt.
- Stats must suit the depth where it first appears (the Balancer enforces a budget: roughly \
max_hp up to 6 + 4 x depth, attack up to 2 + depth // 2).
- Describe `behaviour` precisely, turn by turn, so a Coder can implement it. Describe the \
sprite so it can be drawn in 16x16 pixel art.
- Don't copy an existing monster.

# Game facts
{game_facts()}

# What plugins can do
{capabilities()}"""


class DungeonMasterAgent:
    role = "Dungeon Master"

    def __init__(self, client: anthropic.AsyncAnthropic, config: AgentConfig | None = None) -> None:
        self.client = client
        self.config = config or AgentConfig.for_role("dungeon_master")

    async def design_counter(
        self,
        profile: str,
        depth: int,
        existing_monsters: list[str],
        on_progress: ProgressNote | None = None,
    ) -> tuple[MonsterSpec, Usage]:
        prompt = f"""\
How the player has been fighting:
{profile}

The new monster will first appear at depth {depth}.

Monsters already in the game (don't copy them):
{chr(10).join(f"- {name}" for name in existing_monsters)}"""
        spec, reply = await validated_call(
            self.client,
            self.config,
            system=system_prompt(),
            messages=[{"role": "user", "content": prompt}],
            model=MonsterSpec,
            role=self.role,
            on_progress=on_progress,
        )
        return spec, reply.usage


# ---- the monster pipeline ------------------------------------------------------------------


@dataclass
class MonsterOutcome:
    ok: bool
    spec: MonsterSpec | None = None
    draft: SpellDraft | None = None
    verification: Verification | None = None
    review: dict[str, Any] | None = None
    error: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    seconds: float = 0.0
    usage: Usage = field(default_factory=Usage)
    agents: dict[str, Any] = field(default_factory=dict)

    @property
    def monster_id(self) -> str | None:
        return (
            self.verification.monster.id
            if self.verification and self.verification.monster
            else None
        )


class DungeonMaster:
    """Profile in, a tested counter-monster plugin out."""

    def __init__(
        self,
        agent: DungeonMasterAgent,
        balancer: Balancer,
        coder: Coder,
        artist: Artist | None = None,
        tester: Tester | None = None,
        max_code_attempts: int = DEFAULT_MAX_CODE_ATTEMPTS,
    ) -> None:
        self.agent = agent
        self.balancer = balancer
        self.coder = coder
        self.artist = artist
        self.tester = tester or Tester()
        self.max_code_attempts = max_code_attempts

    async def create_counter(
        self,
        profile: str,
        depth: int,
        existing_monsters: list[str],
        taken_ids: dict[str, list[str]],
        plugin_id: str,
        progress: ProgressCallback = _no_progress,
    ) -> MonsterOutcome:
        started = time.perf_counter()
        outcome = MonsterOutcome(ok=False)
        usage: dict[str, Usage] = defaultdict(Usage)

        def notes(stage: str) -> Any:
            async def note(message: str) -> None:
                await progress(stage, message)

            return note

        art: asyncio.Task[tuple[str, Usage]] | None = None
        sprite_id = f"{plugin_id}_art" if self.artist is not None else None
        try:
            await progress("designing", "The Dungeon Master studies your tactics…")
            spec, used = await self.agent.design_counter(
                profile, depth, existing_monsters, notes("designing")
            )
            usage["dungeon_master"] += used
            await progress("designing", f"Designed “{spec.name}”.", done=True, detail=spec.counters)

            if self.artist is not None:
                art = asyncio.create_task(
                    self.artist.draw(f"{plugin_id}_art", spec.sprite_description, notes("drawing"))
                )
                await progress("drawing", "The Artist starts drawing it…")
            await progress("balancing", "The Balancer checks it is fair…")
            review, used = await self.balancer.review_monster(spec, depth, notes("balancing"))
            usage["balancer"] += used
            outcome.review = {
                "verdict": review.verdict,
                "rationale": review.rationale,
                "changes": [change.model_dump() for change in review.changes],
            }
            await progress(
                "balancing",
                {
                    "approve": "The Balancer approved it.",
                    "adjust": "The Balancer adjusted it.",
                    "reject": "The Balancer rejected it.",
                }[review.verdict],
                done=True,
                verdict=review.verdict,
                detail=review.rationale,
            )
            if review.verdict == "reject":
                outcome.error = f"the Balancer rejected it: {review.rationale}"
                return outcome
            approved = review.spec
            outcome.spec = approved

            task = monster_task(approved, taken_ids, sprite_id)
            await progress("coding", "The Coder is bringing it to life…")
            draft = await self.coder.write(task, [], notes("coding"))
            usage["coder"] += draft.usage
            art_source = None
            if art is not None:
                art_source, used = await art
                usage["artist"] += used
                await progress("drawing", "The Artist finished the sprite.", done=True)
            for attempt in range(1, self.max_code_attempts + 1):
                await progress("testing", "The Tester sets it loose in the arena…")
                draft = _with_art(draft, art_source)
                report = await asyncio.to_thread(
                    self.tester.test_monster, plugin_id, draft.source, approved, taken_ids
                )
                outcome.verification = report
                if report.ok:
                    outcome.ok = True
                    outcome.draft = draft
                    await progress("testing", "It survived the arena.", done=True)
                    break
                outcome.attempts.append(Attempt(draft, report.problems))
                if attempt == self.max_code_attempts:
                    outcome.error = "the monster kept failing its sandbox tests"
                    break
                await progress("retrying", f"The Tester found a problem: {report.problems[0]}")
                draft = await self.coder.write(task, outcome.attempts, notes("coding"))
                usage["coder"] += draft.usage
        except AgentError as exc:
            outcome.error = str(exc)
        finally:
            if art is not None and not art.done():
                art.cancel()
                try:
                    await art
                except (asyncio.CancelledError, AgentError):
                    pass
            outcome.seconds = time.perf_counter() - started
            for used in usage.values():
                outcome.usage = outcome.usage + used
            outcome.agents = {
                role: {"seconds": round(used.seconds, 1), "cost_usd": round(used.cost_usd, 4)}
                for role, used in usage.items()
            }
        return outcome


def _with_art(draft: SpellDraft, art_source: str | None) -> SpellDraft:
    from spellforge.agents.team import TeamForge

    return TeamForge._with_art(draft, art_source)
