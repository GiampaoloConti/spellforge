"""Actions the player can submit. Invalid actions raise `InvalidAction` and cost no turn."""

from __future__ import annotations

from dataclasses import dataclass

from spellforge.engine.geometry import Pos


class InvalidAction(Exception):
    """The action is not allowed right now. Game state is unchanged."""


@dataclass(frozen=True)
class Move:
    """Step one tile in `direction` (a unit `Pos`). Moving into a hostile attacks it."""

    direction: Pos


@dataclass(frozen=True)
class Wait:
    """Do nothing for a turn."""


@dataclass(frozen=True)
class Cast:
    """Cast a known spell. `target` is ignored for self-targeted spells."""

    spell_id: str
    target: Pos | None = None


Action = Move | Wait | Cast
