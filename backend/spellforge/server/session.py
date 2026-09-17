"""One player's game, driven by protocol messages. No networking here, so it is easy to test."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from spellforge.engine import Action, Cast, Game, InvalidAction, Move, Pos, Registry, Wait
from spellforge.narration import Narrator
from spellforge.plugins import default_registry
from spellforge.server.protocol import (
    MAX_MESSAGE_BYTES,
    ActionMessage,
    ActionPayload,
    CastAction,
    MoveAction,
    NewGameMessage,
    client_message,
    error_message,
    state_message,
)

STARTING_SPELLS = ("firebolt", "frost_nova")


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
        registry_factory: Callable[[], Registry] = default_registry,
        rng: random.Random | None = None,
    ) -> None:
        self._registry_factory = registry_factory
        self._rng = rng or random.Random()
        self.game: Game | None = None
        self._narrator: Narrator | None = None

    def handle(self, raw: str) -> dict[str, Any]:
        """Process one raw client message and return the reply to send."""
        if len(raw.encode()) > MAX_MESSAGE_BYTES:
            return error_message("message too large")
        try:
            message = client_message.validate_json(raw)
        except ValidationError as exc:
            return error_message(_describe_validation_error(exc))

        if isinstance(message, NewGameMessage):
            return self._new_game(message.seed)
        assert isinstance(message, ActionMessage)
        return self._act(to_engine_action(message.action))

    def _new_game(self, seed: int | None) -> dict[str, Any]:
        seed = seed if seed is not None else self._rng.randrange(1_000_000)
        self.game = Game.new(seed, self._registry_factory(), spells=STARTING_SPELLS)
        self._narrator = Narrator(self.game)
        log = [f"You enter the dungeon (seed {seed}). Defeat every monster to win."]
        return state_message(self.game, [], log)

    def _act(self, action: Action) -> dict[str, Any]:
        if self.game is None or self._narrator is None:
            return error_message("no game in progress: send new_game first")
        try:
            events = self.game.submit(action)
        except InvalidAction as exc:
            return error_message(str(exc))
        return state_message(self.game, events, self._narrator.narrate(events))
