"""One player's game, driven by protocol messages, plus the forge running beside it.

No networking here: replies and pushed updates go through the `send` callback, so the
session is easy to test. All game mutations happen on the event loop, one message at a
time; the forge only does slow work (the LLM call, sandbox tests) off to the side and
touches the game when it hot-loads a finished spell.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from spellforge.agents.forge import DEFAULT_MAX_ATTEMPTS, forge_spell
from spellforge.agents.spell_writer import SpellRequest, SpellWriter
from spellforge.engine import (
    Action,
    Cast,
    Game,
    GameStatus,
    InvalidAction,
    Move,
    PluginLoadError,
    Pos,
    Registry,
    Wait,
)
from spellforge.narration import Narrator
from spellforge.plugins import default_registry
from spellforge.sandbox.host import PluginSandbox
from spellforge.server.protocol import (
    MAX_MESSAGE_BYTES,
    ActionMessage,
    ActionPayload,
    CastAction,
    InventMessage,
    MoveAction,
    NewGameMessage,
    client_message,
    error_message,
    forge_message,
    state_message,
    welcome_message,
)

logger = logging.getLogger(__name__)

STARTING_SPELLS = ("firebolt", "frost_nova")
MAX_FORGED_SPELLS_PER_GAME = 6
FORGE_OFFLINE = "The forge is offline: add ANTHROPIC_API_KEY to .env and restart the server."

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


class GameSession:
    def __init__(
        self,
        send: Send,
        writer: SpellWriter | None = None,
        registry_factory: Callable[[], Registry] = default_registry,
        rng: random.Random | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._send = send
        self._writer = writer
        self._registry_factory = registry_factory
        self._rng = rng or random.Random()
        self._max_attempts = max_attempts
        self.game: Game | None = None
        self._narrator: Narrator | None = None
        self._sandboxes: list[PluginSandbox] = []
        self._forge_task: asyncio.Task[None] | None = None
        self._forges_started = 0

    async def start(self) -> None:
        status = "ready" if self._writer is not None else FORGE_OFFLINE
        await self._send(welcome_message(self._writer is not None, status))

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

    async def close(self) -> None:
        """Stop the forge and every plugin process. Call when the connection ends."""
        await self._cancel_forge()
        self._close_sandboxes()

    # ---- game ------------------------------------------------------------------

    async def _new_game(self, seed: int | None) -> None:
        if await self._cancel_forge():
            await self._send(forge_message("failed", "The forge was stopped: a new run began."))
        self._close_sandboxes()
        seed = seed if seed is not None else self._rng.randrange(1_000_000)
        self.game = Game.new(seed, self._registry_factory(), spells=STARTING_SPELLS)
        self._narrator = Narrator(self.game)
        log = [f"You enter the dungeon (seed {seed}). Defeat every monster to win."]
        await self._send(state_message(self.game, [], log))

    async def _act(self, action: Action) -> None:
        if self.game is None or self._narrator is None:
            await self._send(error_message("no game in progress: send new_game first"))
            return
        try:
            events = self.game.submit(action)
        except InvalidAction as exc:
            await self._send(error_message(str(exc)))
            return
        await self._send(state_message(self.game, events, self._narrator.narrate(events)))

    # ---- forge -----------------------------------------------------------------

    async def _invent(self, idea: str) -> None:
        game = self.game
        problem = (
            FORGE_OFFLINE
            if self._writer is None
            else "Start a game first."
            if game is None
            else "The run is over: start a new game to forge spells."
            if game.status is not GameStatus.PLAYING
            else "The forge is already working on a spell."
            if self._forge_task is not None
            else f"Your spellbook is full: at most {MAX_FORGED_SPELLS_PER_GAME} forged spells."
            if self._forged_count(game) >= MAX_FORGED_SPELLS_PER_GAME
            else None
        )
        if problem is not None or game is None or self._writer is None:
            await self._send(forge_message("failed", problem or "The forge is unavailable."))
            return

        self._forges_started += 1
        registry = game.registry
        request = SpellRequest(
            idea=idea,
            taken_ids={
                "spells": sorted(registry.spells),
                "statuses": sorted(registry.statuses),
                "monsters": sorted(registry.monsters),
            },
            known_spells=[
                f"{s.name} ({s.mana_cost} mana): {s.description}"
                for s in (registry.spells[i] for i in game.spellbook)
            ],
        )
        await self._send(forge_message("started", "The arcane forge takes your idea…", idea=idea))
        self._forge_task = asyncio.create_task(
            self._run_forge(game, request, f"forged_{self._forges_started}")
        )

    def _forged_count(self, game: Game) -> int:
        return sum(1 for plugin_id in game.registry.plugins if plugin_id.startswith("forged_"))

    async def _run_forge(self, game: Game, request: SpellRequest, plugin_id: str) -> None:
        assert self._writer is not None

        async def progress(stage: str, message: str) -> None:
            await self._send(forge_message("working", message, stage=stage))

        try:
            outcome = await forge_spell(
                request, self._writer, plugin_id, self._max_attempts, progress
            )
            if not outcome.ok or outcome.draft is None:
                problems = outcome.attempts[-1].problems[:3] if outcome.attempts else []
                await self._send(
                    forge_message(
                        "failed", f"The forge failed: {outcome.error}.", problems=problems
                    )
                )
                return

            await progress("loading", "Binding the spell into your spellbook…")
            draft = outcome.draft
            sandbox, plugin = await asyncio.to_thread(PluginSandbox.start, plugin_id, draft.source)
            if game is not self.game or game.status is not GameStatus.PLAYING:
                sandbox.close()
                return
            try:
                game.load_plugin(plugin)
            except PluginLoadError as exc:
                sandbox.close()
                await self._send(forge_message("failed", f"The spell could not be added: {exc}"))
                return
            self._sandboxes.append(sandbox)
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
                    state=snapshot,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("forge crashed")
            await self._send(forge_message("failed", "The forge broke down unexpectedly."))
        finally:
            if self._forge_task is asyncio.current_task():
                self._forge_task = None

    async def _cancel_forge(self) -> bool:
        task, self._forge_task = self._forge_task, None
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
