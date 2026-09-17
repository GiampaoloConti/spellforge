"""The in-process implementation of `Ctx`. Validates every argument coming from plugins.

Plugin code is untrusted input: arguments are checked here, and misuse raises
`PluginError`. Dead or unknown entity ids are tolerated (see `Ctx` docs).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from spellforge.engine.api import FACTIONS, Ctx, EntityView, PluginError
from spellforge.engine.events import EventType
from spellforge.engine.geometry import Pos, line

if TYPE_CHECKING:
    from spellforge.engine.entity import Entity
    from spellforge.engine.game import Game

T = TypeVar("T")

MAX_AMOUNT = 1_000
MAX_DISTANCE = 100


def _as_int(value: Any, what: str, low: int = -(10**6), high: int = 10**6) -> int:
    """Accept ints and finite floats (rounded), reject everything else."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PluginError(f"{what} must be a number, got {type(value).__name__}")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PluginError(f"{what} must be finite")
        value = round(value)
    if not low <= value <= high:
        raise PluginError(f"{what} must be between {low} and {high}, got {value}")
    return value


def _as_id(value: Any, what: str = "entity id") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PluginError(f"{what} must be an int id (use view.id), got {type(value).__name__}")
    return value


def _as_pos(value: Any, what: str = "position") -> Pos:
    if isinstance(value, Pos):
        return value
    if isinstance(value, tuple | list) and len(value) == 2:
        return Pos(_as_int(value[0], f"{what}.x"), _as_int(value[1], f"{what}.y"))
    raise PluginError(f"{what} must be a Pos, got {type(value).__name__}")


def _as_str(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise PluginError(f"{what} must be a string, got {type(value).__name__}")
    return value


def _as_faction(value: Any) -> str | None:
    if value is not None and value not in FACTIONS:
        raise PluginError(f"faction must be one of {FACTIONS} or None, got {value!r}")
    return value


class GameContext(Ctx):
    def __init__(self, game: Game) -> None:
        self._game = game

    def _living(self, entity_id: Any) -> Entity | None:
        entity = self._game.entities.get(_as_id(entity_id))
        return entity if entity is not None and entity.alive else None

    # ---- queries -------------------------------------------------------------

    def turn_number(self) -> int:
        self._game.count_op()
        return self._game.turn

    def player(self) -> EntityView:
        self._game.count_op()
        return self._game.player.view()

    def entity(self, entity_id: int) -> EntityView | None:
        self._game.count_op()
        entity = self._game.entities.get(_as_id(entity_id))
        return entity.view() if entity is not None else None

    def entity_at(self, pos: Pos) -> EntityView | None:
        self._game.count_op()
        entity = self._game.living_entity_at(_as_pos(pos))
        return entity.view() if entity is not None else None

    def entities(self, faction: str | None = None) -> list[EntityView]:
        self._game.count_op()
        faction = _as_faction(faction)
        return [
            e.view()
            for e in self._game.entities.values()
            if e.alive and (faction is None or e.faction == faction)
        ]

    def entities_in_radius(
        self, center: Pos, radius: int, faction: str | None = None
    ) -> list[EntityView]:
        self._game.count_op()
        center = _as_pos(center, "center")
        radius = _as_int(radius, "radius", 0, MAX_DISTANCE)
        faction = _as_faction(faction)
        return [
            e.view()
            for e in self._game.entities.values()
            if e.alive
            and e.pos.distance_to(center) <= radius
            and (faction is None or e.faction == faction)
        ]

    def nearest_hostile(
        self, entity_id: int, max_distance: int, require_line_of_sight: bool = True
    ) -> EntityView | None:
        self._game.count_op()
        max_distance = _as_int(max_distance, "max_distance", 0, MAX_DISTANCE)
        me = self._living(entity_id)
        if me is None:
            return None
        candidates = [
            e
            for e in self._game.entities.values()
            if e.alive
            and e.faction != me.faction
            and e.pos.distance_to(me.pos) <= max_distance
            and (not require_line_of_sight or self._game.map.has_line_of_sight(me.pos, e.pos))
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda e: (e.pos.distance_to(me.pos), e.id)).view()

    def is_wall(self, pos: Pos) -> bool:
        self._game.count_op()
        return self._game.map.is_wall(_as_pos(pos))

    def is_walkable(self, pos: Pos) -> bool:
        self._game.count_op()
        return self._game.is_walkable(_as_pos(pos))

    def line(self, start: Pos, end: Pos) -> list[Pos]:
        self._game.count_op()
        start, end = _as_pos(start, "start"), _as_pos(end, "end")
        if start.distance_to(end) > MAX_DISTANCE:
            raise PluginError(f"line longer than {MAX_DISTANCE} tiles")
        return line(start, end)

    def has_line_of_sight(self, start: Pos, end: Pos) -> bool:
        self._game.count_op()
        start, end = _as_pos(start, "start"), _as_pos(end, "end")
        if start.distance_to(end) > MAX_DISTANCE:
            return False
        return self._game.map.has_line_of_sight(start, end)

    def has_status(self, entity_id: int, status_id: str) -> bool:
        self._game.count_op()
        status_id = _as_str(status_id, "status_id")
        entity = self._living(entity_id)
        return entity is not None and status_id in entity.statuses

    def random_int(self, low: int, high: int) -> int:
        self._game.count_op()
        low, high = _as_int(low, "low"), _as_int(high, "high")
        if low > high:
            raise PluginError(f"random_int low ({low}) is greater than high ({high})")
        return self._game.rng.randint(low, high)

    def chance(self, probability: float) -> bool:
        self._game.count_op()
        if isinstance(probability, bool) or not isinstance(probability, int | float):
            raise PluginError("probability must be a number between 0 and 1")
        if not 0.0 <= probability <= 1.0:
            raise PluginError(f"probability must be between 0 and 1, got {probability}")
        return self._game.rng.random() < probability

    def choice(self, options: Sequence[T]) -> T:
        self._game.count_op()
        if not isinstance(options, list | tuple) or not options:
            raise PluginError("choice needs a non-empty list or tuple")
        return options[self._game.rng.randrange(len(options))]

    # ---- actions -------------------------------------------------------------

    def damage(self, target: int, amount: int, source: int | None = None) -> int:
        self._game.count_op()
        amount = _as_int(amount, "damage amount", 0, MAX_AMOUNT)
        if source is not None:
            _as_id(source, "source")
        entity = self._living(target)
        return self._game.damage(entity, amount, source) if entity is not None else 0

    def heal(self, target: int, amount: int) -> int:
        self._game.count_op()
        amount = _as_int(amount, "heal amount", 0, MAX_AMOUNT)
        entity = self._living(target)
        return self._game.heal(entity, amount) if entity is not None else 0

    def attack(self, attacker: int, target: int) -> int:
        self._game.count_op()
        a, t = self._living(attacker), self._living(target)
        if a is None or t is None or a is t or a.pos.distance_to(t.pos) != 1:
            return 0
        return self._game.melee(a, t)

    def move(self, entity_id: int, pos: Pos) -> bool:
        self._game.count_op()
        pos = _as_pos(pos)
        entity = self._living(entity_id)
        if entity is None or entity.pos.distance_to(pos) != 1 or not self._game.is_walkable(pos):
            return False
        self._game.move_entity(entity, pos, "step")
        return True

    def step_toward(self, entity_id: int, goal: Pos) -> bool:
        self._game.count_op()
        goal = _as_pos(goal, "goal")
        entity = self._living(entity_id)
        if entity is None:
            return False
        step = self._game.first_step_toward(entity.pos, goal)
        if step is None:
            return False
        self._game.move_entity(entity, step, "step")
        return True

    def teleport(self, entity_id: int, pos: Pos) -> bool:
        self._game.count_op()
        pos = _as_pos(pos)
        entity = self._living(entity_id)
        if entity is None or not self._game.is_walkable(pos):
            return False
        self._game.move_entity(entity, pos, "teleport")
        return True

    def push(self, entity_id: int, away_from: Pos, distance: int) -> int:
        self._game.count_op()
        away_from = _as_pos(away_from, "away_from")
        distance = _as_int(distance, "push distance", 0, 20)
        entity = self._living(entity_id)
        if entity is None:
            return 0
        direction = away_from.direction_to(entity.pos)
        if direction == Pos(0, 0):
            return 0
        dest = entity.pos
        moved = 0
        while moved < distance and self._game.is_walkable(dest + direction):
            dest = dest + direction
            moved += 1
        if moved:
            self._game.move_entity(entity, dest, "push")
        return moved

    def apply_status(
        self, target: int, status_id: str, duration: int | None, source: int | None = None
    ) -> bool:
        self._game.count_op()
        status_id = _as_str(status_id, "status_id")
        sdef = self._game.registry.statuses.get(status_id)
        if sdef is None:
            raise PluginError(f"unknown status {status_id!r}; define it with define_status")
        if duration is not None:
            duration = _as_int(duration, "duration", 1, 100)
        elif sdef.prevents_action:
            raise PluginError(f"status {status_id!r} prevents action, so it needs a duration")
        if source is not None:
            _as_id(source, "source")
        entity = self._living(target)
        if entity is None:
            return False
        return self._game.apply_status(entity, status_id, duration, source)

    def remove_status(self, target: int, status_id: str) -> bool:
        self._game.count_op()
        status_id = _as_str(status_id, "status_id")
        entity = self._living(target)
        return entity is not None and self._game.remove_status(entity, status_id)

    def spawn(self, monster_id: str, pos: Pos, faction: str = "enemy") -> int | None:
        self._game.count_op()
        monster_id = _as_str(monster_id, "monster_id")
        if monster_id not in self._game.registry.monsters:
            raise PluginError(f"unknown monster {monster_id!r}; define it with define_monster")
        pos = _as_pos(pos)
        if _as_faction(faction) is None:
            raise PluginError("spawn faction cannot be None")
        entity = self._game.spawn(monster_id, pos, faction)
        return entity.id if entity is not None else None

    def log(self, message: str) -> None:
        self._game.count_op()
        self._game.emit(EventType.MESSAGE, text=_as_str(message, "message")[:200])
