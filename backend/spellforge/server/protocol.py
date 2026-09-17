"""The websocket protocol between the browser and the server, as validated models.

Client -> server messages are parsed with pydantic, so anything malformed is rejected
before it reaches the engine. Server -> client messages are built by the helpers
below. Keep `frontend/src/protocol.ts` in sync with this file.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from spellforge.engine import Event, Game


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- client -> server --------------------------------------------------------


class MoveAction(_Message):
    kind: Literal["move"]
    dx: int = Field(ge=-1, le=1)
    dy: int = Field(ge=-1, le=1)


class WaitAction(_Message):
    kind: Literal["wait"]


class CastAction(_Message):
    kind: Literal["cast"]
    spell: str = Field(max_length=40)
    target: tuple[int, int] | None = None


ActionPayload = Annotated[MoveAction | WaitAction | CastAction, Field(discriminator="kind")]


class NewGameMessage(_Message):
    type: Literal["new_game"]
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class ActionMessage(_Message):
    type: Literal["action"]
    action: ActionPayload


class InventMessage(_Message):
    """Ask the forge to write a new spell from the player's description."""

    type: Literal["invent"]
    idea: str = Field(min_length=3, max_length=300)


ClientMessage = Annotated[
    NewGameMessage | ActionMessage | InventMessage, Field(discriminator="type")
]
client_message = TypeAdapter(ClientMessage)

MAX_MESSAGE_BYTES = 4096


# ---- server -> client --------------------------------------------------------


def state_message(game: Game, events: list[Event], log: list[str]) -> dict[str, Any]:
    """The full game state after something happened, plus what happened."""
    return {
        "type": "state",
        "state": game.snapshot(),
        "events": [event.to_dict() for event in events],
        "log": log,
    }


def error_message(message: str) -> dict[str, Any]:
    """Something was rejected. The game state is unchanged."""
    return {"type": "error", "message": message}


def welcome_message(forge_available: bool, forge_status: str) -> dict[str, Any]:
    """Sent once when a client connects."""
    return {"type": "welcome", "forge_available": forge_available, "forge_status": forge_status}


def forge_message(status: str, message: str, **fields: Any) -> dict[str, Any]:
    """Progress of a spell being forged, pushed while the game keeps running.

    status: "started" | "working" | "done" | "failed". "done" carries the new spell, its
    source code and the updated game state.
    """
    return {"type": "forge", "status": status, "message": message, **fields}
