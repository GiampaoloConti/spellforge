"""Events: the record of everything that happened, consumed by renderers, logs and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    MOVED = "moved"  # entity, from, to, how ("step" | "teleport" | "push")
    ATTACKED = "attacked"  # attacker, target
    DAMAGED = "damaged"  # target, pos, amount, source, hp
    HEALED = "healed"  # target, pos, amount, hp
    DIED = "died"  # entity, pos
    SPAWNED = "spawned"  # entity, kind, pos, faction
    STATUS_APPLIED = "status_applied"  # entity, status, remaining, refreshed
    STATUS_EXPIRED = "status_expired"  # entity, status
    STATUS_REMOVED = "status_removed"  # entity, status
    SPELL_CAST = "spell_cast"  # caster, spell, target
    TURN_SKIPPED = "turn_skipped"  # entity
    MESSAGE = "message"  # text
    PLUGIN_DISABLED = "plugin_disabled"  # plugin, reason
    LEVEL_CLEARED = "level_cleared"  # depth, stairs
    LEVEL_STARTED = "level_started"  # depth
    GAME_OVER = "game_over"  # result ("lost"), depth


@dataclass(frozen=True)
class Event:
    type: EventType
    turn: int
    data: dict[str, Any] = field(default_factory=dict)
    """JSON-ready values only: ints, strings, None, [x, y] lists."""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "turn": self.turn, **self.data}
