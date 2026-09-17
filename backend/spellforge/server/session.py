"""One player's game, driven by protocol messages, with two agent pipelines beside it.

- The forge turns the player's spell ideas into plugins (the agent team, or one agent).
  Each spell costs an arcane shard, found every third level; a failed forge gives it back.
- The Dungeon Master designs counter-monsters when the player clears a level.

No networking here: replies and pushed updates go through the `send` callback, so the
session is easy to test. All game mutations happen on the event loop, one message at a time;
the pipelines do their slow work (LLM calls, sandbox tests) off to the side and only touch
the game when they hot-load a finished plugin.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from spellforge.agents.dungeon_master import DungeonMaster, MonsterOutcome, profile_player
from spellforge.agents.forge import SpellForge
from spellforge.agents.spell_writer import SpellRequest
from spellforge.engine import (
    ARCANE_SHARD,
    Action,
    Cast,
    Event,
    EventType,
    Game,
    GameStatus,
    InvalidAction,
    Move,
    Plugin,
    PluginLoadError,
    Pos,
    Registry,
    Wait,
)
from spellforge.engine.game import SHARD_EVERY
from spellforge.narration import Narrator
from spellforge.plugins import builtin_encounters, default_registry
from spellforge.sandbox.host import PluginSandbox
from spellforge.server.limits import Reservation, SpendingCap
from spellforge.server.protocol import (
    MAX_MESSAGE_BYTES,
    ActionMessage,
    ActionPayload,
    CastAction,
    DevMessage,
    InventMessage,
    MoveAction,
    NewGameMessage,
    client_message,
    dungeon_master_message,
    error_message,
    forge_message,
    state_message,
    welcome_message,
)

logger = logging.getLogger(__name__)

STARTING_SPELLS = ("firebolt", "frost_nova")
MAX_FORGED_SPELLS_PER_GAME = 6
MAX_COUNTER_MONSTERS_PER_GAME = 3
COUNTER_MONSTER_WEIGHT = 5
"""Encounter weight of a Dungeon Master monster: high, so the player actually meets it."""
FORGE_OFFLINE = "The forge is offline: add ANTHROPIC_API_KEY to .env and restart the server."
NEEDS_SHARD = (
    "The Arcane Forge needs an arcane shard. One lies hidden on depths 1, "
    f"{1 + SHARD_EVERY}, {1 + 2 * SHARD_EVERY}, ... Find it and step on it."
)
BUDGET_SPENT = (
    "The forge has used up today's budget of AI credit. It rekindles tomorrow (UTC); "
    "until then, the dungeon awaits."
)

Send = Callable[[dict[str, Any]], Awaitable[None]]


def to_engine_action(payload: ActionPayload) -> Action:
    if isinstance(payload, MoveAction):
        return Move(Pos(payload.dx, payload.dy))
    if isinstance(payload, CastAction):
        target = Pos(*payload.target) if payload.target is not None else None
        return Cast(payload.spell, target)
    return Wait()


def _describe_validation_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"malformed message: {where + ': ' if where else ''}{first['msg']}"


def _taken_ids(registry: Registry) -> dict[str, list[str]]:
    return {
        "spells": sorted(registry.spells),
        "statuses": sorted(registry.statuses),
        "monsters": sorted(registry.monsters),
        "sprites": sorted(registry.sprites),
    }


class GameSession:
    def __init__(
        self,
        send: Send,
        forge: SpellForge | None = None,
        dungeon_master: DungeonMaster | None = None,
        registry_factory: Callable[[], Registry] = default_registry,
        rng: random.Random | None = None,
        dev_tools: bool = False,
        spending: SpendingCap | None = None,
    ) -> None:
        self._send = send
        self._dev_tools = dev_tools
        self._spending = spending or SpendingCap(None)
        self._forge = forge
        self._dungeon_master = dungeon_master
        self._registry_factory = registry_factory
        self._rng = rng or random.Random()
        self.game: Game | None = None
        self._narrator: Narrator | None = None
        self._sandboxes: list[PluginSandbox] = []
        self._forge_task: asyncio.Task[None] | None = None
        self._dm_task: asyncio.Task[None] | None = None
        self._plugins_started = 0
        self._sent_sprites: set[str] = set()
        self.counter_monsters: list[tuple[str, int]] = []
        """(monster id, first depth) for each Dungeon Master monster in this run."""

    async def start(self) -> None:
        await self._send(
            welcome_message(
                self._forge is not None,
                "ready" if self._forge is not None else FORGE_OFFLINE,
                forge_mode=self._forge.mode if self._forge is not None else None,
                dungeon_master=self._dungeon_master is not None,
            )
        )

    async def handle(self, raw: str) -> None:
        """Process one raw client message. Replies (and later pushes) go through `send`."""
        if len(raw.encode()) > MAX_MESSAGE_BYTES:
            await self._send(error_message("message too large"))
            return
        try:
            message = client_message.validate_json(raw)
        except ValidationError as exc:
            await self._send(error_message(_describe_validation_error(exc)))
            return

        if isinstance(message, NewGameMessage):
            await self._new_game(message.seed)
        elif isinstance(message, ActionMessage):
            await self._act(to_engine_action(message.action))
        elif isinstance(message, InventMessage):
            await self._invent(message.idea.strip())
        elif isinstance(message, DevMessage):
            await self._dev(message)

    async def close(self) -> None:
        """Stop both pipelines and every plugin process. Call when the connection ends."""
        await self._cancel(self._forge_task)
        await self._cancel(self._dm_task)
        self._forge_task = self._dm_task = None
        self._close_sandboxes()

    # ---- game ------------------------------------------------------------------

    async def _new_game(self, seed: int | None) -> None:
        if await self._cancel(self._forge_task):
            await self._send(forge_message("failed", "The forge was stopped: a new run began."))
        await self._cancel(self._dm_task)
        self._forge_task = self._dm_task = None
        self._close_sandboxes()
        self.counter_monsters = []
        seed = seed if seed is not None else self._rng.randrange(1_000_000)
        self.game = Game.new(
            seed, self._registry_factory(), spells=STARTING_SPELLS, encounters=self.encounters
        )
        self._narrator = Narrator(self.game)
        self._sent_sprites.clear()
        log = [
            f"You enter the dungeon (seed {seed}). Clear each level to open the stairs down, "
            "and see how deep you can go.",
            "An arcane shard glimmers somewhere on this level: it powers the Arcane Forge.",
        ]
        await self._send(state_message(self.game, [], log, self._unsent_sprites(self.game)))

    def encounters(self, depth: int) -> list[tuple[str, int]]:
        """Builtin monsters plus the Dungeon Master's counters that have reached this depth."""
        table = builtin_encounters(depth)
        table += [
            (monster_id, COUNTER_MONSTER_WEIGHT)
            for monster_id, first_depth in self.counter_monsters
            if depth >= first_depth
        ]
        return table

    async def _act(self, action: Action) -> None:
        if self.game is None or self._narrator is None:
            await self._send(error_message("no game in progress: send new_game first"))
            return
        try:
            events = self.game.submit(action)
        except InvalidAction as exc:
            await self._send(error_message(str(exc)))
            return
        await self._after(self.game, events)

    async def _after(self, game: Game, events: list[Event]) -> None:
        """Send what happened, and react to it (a cleared level summons the Dungeon Master)."""
        assert self._narrator is not None
        await self._send(
            state_message(game, events, self._narrator.narrate(events), self._unsent_sprites(game))
        )
        if any(event.type is EventType.LEVEL_CLEARED for event in events):
            await self._summon_dungeon_master(game)

    async def _dev(self, message: DevMessage) -> None:
        if not self._dev_tools:
            await self._send(error_message("dev tools are disabled on this server"))
            return
        game = self.game
        if game is None or game.status is not GameStatus.PLAYING:
            await self._send(error_message("no game in progress"))
            return
        start = len(game.history)
        if message.command == "clear_level":
            for enemy in [e for e in game.entities.values() if e.faction != game.player.faction]:
                game.kill(enemy)
            await self._after(game, game.history[start:])
        elif message.command == "descend":
            stairs = game.stairs
            beside = [p for p in stairs.neighbors() if game.is_walkable(p)] if stairs else []
            if stairs is None or not beside:
                await self._send(error_message("the stairs are not open"))
                return
            game.player.pos = beside[0]
            await self._act(Move(beside[0].direction_to(stairs)))
        elif message.command == "give_shard":
            game.add_item(ARCANE_SHARD)
            await self._after(game, game.history[start:])

    def _unsent_sprites(self, game: Game) -> dict[str, Any]:
        new_ids = set(game.registry.sprites) - self._sent_sprites
        self._sent_sprites |= new_ids
        return game.sprite_art(new_ids) if new_ids else {}

    def _next_plugin_id(self, prefix: str) -> str:
        self._plugins_started += 1
        return f"{prefix}_{self._plugins_started}"

    async def _hot_load(self, game: Game, plugin_id: str, source: str) -> Plugin | None:
        """Start a sandbox for a verified plugin and add it to the game.

        Returns None if the run ended meanwhile. Raises PluginLoadError on id clashes.
        """
        sandbox, plugin = await asyncio.to_thread(PluginSandbox.start, plugin_id, source)
        if game is not self.game or game.status is not GameStatus.PLAYING:
            sandbox.close()
            return None
        try:
            game.load_plugin(plugin)
        except PluginLoadError:
            sandbox.close()
            raise
        self._sandboxes.append(sandbox)
        return plugin

    # ---- forge -----------------------------------------------------------------

    async def _invent(self, idea: str) -> None:
        game = self.game
        problem = (
            FORGE_OFFLINE
            if self._forge is None
            else "Start a game first."
            if game is None
            else "The run is over: start a new game to forge spells."
            if game.status is not GameStatus.PLAYING
            else "The forge is already working on a spell."
            if self._forge_task is not None
            else f"Your spellbook is full: at most {MAX_FORGED_SPELLS_PER_GAME} forged spells."
            if self._forged_count(game) >= MAX_FORGED_SPELLS_PER_GAME
            else NEEDS_SHARD
            if game.inventory.get(ARCANE_SHARD, 0) < 1
            else BUDGET_SPENT
            if not self._spending.available()
            else None
        )
        reservation = self._spending.reserve() if problem is None else None
        if problem is not None or game is None or self._forge is None or reservation is None:
            await self._send(forge_message("failed", problem or "The forge is unavailable."))
            return

        registry = game.registry
        request = SpellRequest(
            idea=idea,
            taken_ids=_taken_ids(registry),
            known_spells=[
                f"{s.name} ({s.mana_cost} mana): {s.description}"
                for s in (registry.spells[i] for i in game.spellbook)
            ],
        )
        game.use_item(ARCANE_SHARD)
        await self._send(
            forge_message(
                "started",
                "The arcane forge consumes a shard and takes your idea…",
                idea=idea,
                mode=self._forge.mode,
                state=game.snapshot(),
            )
        )
        self._forge_task = asyncio.create_task(
            self._run_forge(game, request, self._next_plugin_id("forged"), reservation)
        )

    def _forged_count(self, game: Game) -> int:
        return sum(1 for plugin_id in game.registry.plugins if plugin_id.startswith("forged_"))

    async def _run_forge(
        self, game: Game, request: SpellRequest, plugin_id: str, reservation: Reservation
    ) -> None:
        assert self._forge is not None
        cost: float | None = None

        async def progress(stage: str, message: str, **details: Any) -> None:
            await self._send(forge_message("working", message, stage=stage, **details))

        async def fail(message: str, **details: Any) -> None:
            if game is not self.game or game.status is not GameStatus.PLAYING:
                return
            game.add_item(ARCANE_SHARD)
            await self._send(
                forge_message(
                    "failed",
                    f"{message} Your arcane shard is returned.",
                    state=game.snapshot(),
                    **details,
                )
            )

        try:
            outcome = await self._forge.forge(request, plugin_id, progress)
            cost = outcome.cost_usd
            if not outcome.ok or outcome.draft is None:
                problems = outcome.attempts[-1].problems[:3] if outcome.attempts else []
                await fail(
                    f"The forge failed: {outcome.error}.", problems=problems, team=outcome.team
                )
                return

            await progress("loading", "Binding the spell into your spellbook…")
            draft = outcome.draft
            try:
                plugin = await self._hot_load(game, plugin_id, draft.source)
            except PluginLoadError as exc:
                await fail(f"The spell could not be added: {exc}.")
                return
            if plugin is None:
                return
            spell = plugin.spells[0]
            game.learn_spell(spell.id)

            snapshot = game.snapshot()
            await self._send(
                forge_message(
                    "done",
                    f"{spell.name} has been forged and added to your spellbook.",
                    spell=next(s for s in snapshot["spells"] if s["id"] == spell.id),
                    notes=draft.notes,
                    source=draft.source,
                    warnings=outcome.verification.warnings if outcome.verification else [],
                    attempts=len(outcome.attempts) + 1,
                    seconds=round(outcome.seconds, 1),
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                    cost_usd=round(outcome.cost_usd, 4),
                    team=outcome.team,
                    state=snapshot,
                    sprites=self._unsent_sprites(game),
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("forge crashed")
            await fail("The forge broke down unexpectedly.")
        finally:
            self._spending.settle(reservation, cost)
            if self._forge_task is asyncio.current_task():
                self._forge_task = None

    # ---- dungeon master --------------------------------------------------------

    async def _summon_dungeon_master(self, game: Game) -> None:
        if (
            self._dungeon_master is None
            or self._narrator is None
            or self._dm_task is not None
            or len(self.counter_monsters) >= MAX_COUNTER_MONSTERS_PER_GAME
        ):
            return
        reservation = self._spending.reserve()
        if reservation is None:
            return  # today's budget is used up: the dungeon just stays as it is
        first_depth = game.depth + 1
        profile = profile_player(game, self._narrator.names)
        existing = [f"{m.name}: {m.description}" for m in game.registry.monsters.values()]
        await self._send(
            dungeon_master_message(
                "started", "The Dungeon Master has been watching how you fight…", depth=first_depth
            )
        )
        self._dm_task = asyncio.create_task(
            self._run_dungeon_master(
                game, profile, first_depth, existing, self._next_plugin_id("dm"), reservation
            )
        )

    async def _run_dungeon_master(
        self,
        game: Game,
        profile: str,
        first_depth: int,
        existing: list[str],
        plugin_id: str,
        reservation: Reservation,
    ) -> None:
        assert self._dungeon_master is not None
        cost: float | None = None

        async def progress(stage: str, message: str, **details: Any) -> None:
            await self._send(dungeon_master_message("working", message, stage=stage, **details))

        try:
            outcome: MonsterOutcome = await self._dungeon_master.create_counter(
                profile, first_depth, existing, _taken_ids(game.registry), plugin_id, progress
            )
            cost = outcome.usage.cost_usd
            if not outcome.ok or outcome.draft is None or outcome.spec is None:
                await self._send(
                    dungeon_master_message(
                        "failed", f"The Dungeon Master's plan fell apart: {outcome.error}."
                    )
                )
                return
            try:
                plugin = await self._hot_load(game, plugin_id, outcome.draft.source)
            except PluginLoadError as exc:
                await self._send(dungeon_master_message("failed", f"The monster escaped: {exc}"))
                return
            if plugin is None:
                return
            monster = plugin.monsters[0]
            self.counter_monsters.append((monster.id, first_depth))
            spec = outcome.spec
            await self._send(
                dungeon_master_message(
                    "done",
                    f"The Dungeon Master unleashes the {spec.name}. It hunts you from depth "
                    f"{first_depth}.",
                    monster={
                        "id": monster.id,
                        "name": spec.name,
                        "description": spec.description,
                        "counters": spec.counters,
                        "weakness": spec.weakness,
                        "taunt": spec.taunt,
                        "sprite": monster.sprite,
                        "max_hp": monster.max_hp,
                        "attack": monster.attack,
                        "first_depth": first_depth,
                    },
                    review=outcome.review,
                    source=outcome.draft.source,
                    seconds=round(outcome.seconds, 1),
                    cost_usd=round(outcome.usage.cost_usd, 4),
                    sprites=self._unsent_sprites(game),
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("dungeon master crashed")
            await self._send(dungeon_master_message("failed", "The Dungeon Master lost the plot."))
        finally:
            self._spending.settle(reservation, cost)
            if self._dm_task is asyncio.current_task():
                self._dm_task = None

    # ---- helpers ---------------------------------------------------------------

    @staticmethod
    async def _cancel(task: asyncio.Task[None] | None) -> bool:
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    def _close_sandboxes(self) -> None:
        for sandbox in self._sandboxes:
            sandbox.close()
        self._sandboxes.clear()
