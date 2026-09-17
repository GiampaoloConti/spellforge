"""The Spellforge plugin API: the only surface plugin code may touch.

Everything in this module is part of the contract with plugin authors, including the
AI Coder agent, which receives these docstrings as documentation. Keep it small,
explicit and stable.

Design rules:

* Plugins never hold live engine objects. They see entities through read-only
  `EntityView` snapshots and refer to them by integer id.
* Plugins change the game only by calling methods on `ctx`. The engine validates
  every call, so a buggy plugin cannot corrupt state.
* Only plain data crosses the boundary (ints, strings, `Pos`, views), which lets
  the engine later run plugins in a separate sandboxed process.
* All randomness comes from `ctx`, which is seeded, so games replay exactly.
"""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from spellforge.engine.geometry import Pos

T = TypeVar("T")

PLAYER_FACTION = "player"
ENEMY_FACTION = "enemy"
FACTIONS = (PLAYER_FACTION, ENEMY_FACTION)


class PluginError(Exception):
    """Raised when plugin code misuses the API. The engine disables the offending plugin."""


# --------------------------------------------------------------------------- views


@dataclass(frozen=True, slots=True)
class EntityView:
    """A read-only snapshot of a creature at the moment you asked for it.

    Snapshots do not update: after calling an action such as `ctx.damage`, ask
    `ctx.entity(id)` again to see the new state.
    """

    id: int
    kind: str
    """"player" for the player, otherwise the monster id (e.g. "goblin")."""
    name: str
    glyph: str
    faction: str
    """"player" (the player and their allies) or "enemy"."""
    pos: Pos
    hp: int
    max_hp: int
    mana: int
    max_mana: int
    attack: int
    """Melee damage dealt by `ctx.attack`."""
    statuses: tuple[str, ...]
    """Ids of the statuses currently on this entity."""
    alive: bool
    """False only inside `on_death` hooks, while the entity is being removed."""

    @property
    def is_player(self) -> bool:
        return self.kind == "player"


@dataclass(frozen=True, slots=True)
class StatusView:
    """A status instance, as passed to status hooks."""

    status_id: str
    holder: int
    """Id of the entity carrying the status."""
    remaining: int | None
    """Holder turns left before it expires, or None if permanent."""
    source: int | None
    """Id of the entity that applied it, if any."""


# --------------------------------------------------------------------- definitions


class Target(StrEnum):
    """How a spell picks its target tile."""

    SELF = "self"
    """No choice: the target is the caster's own tile."""
    TILE = "tile"
    """Any non-wall tile within range."""
    ENTITY = "entity"
    """A tile within range that holds a living creature."""


SpellCast = Callable[["Ctx", int, Pos], None]
StatusHook = Callable[["Ctx", StatusView], None]
DamagedHook = Callable[["Ctx", StatusView, int, "int | None"], None]
MonsterAct = Callable[["Ctx", int], None]


@dataclass(frozen=True)
class SpellDef:
    id: str
    name: str
    description: str
    mana_cost: int
    cooldown: int
    target: Target
    range: int
    requires_line_of_sight: bool
    on_cast: SpellCast
    plugin_id: str


@dataclass(frozen=True)
class StatusDef:
    id: str
    name: str
    description: str
    prevents_action: bool
    on_apply: StatusHook | None
    on_turn: StatusHook | None
    on_expire: StatusHook | None
    on_damaged: DamagedHook | None
    on_death: StatusHook | None
    plugin_id: str


@dataclass(frozen=True)
class MonsterDef:
    id: str
    name: str
    description: str
    glyph: str
    max_hp: int
    attack: int
    act: MonsterAct | None
    plugin_id: str


# ------------------------------------------------------------------------- context


class Ctx(ABC):
    """Your handle on the running game, passed as the first argument to every hook.

    Query methods return plain values or `EntityView` snapshots. Action methods
    change the game and return what actually happened (e.g. damage dealt). Passing an
    invalid argument raises `PluginError`, and the engine then disables your plugin,
    so validate targets with the query methods first. Dead or unknown entity ids are
    NOT errors: actions on them do nothing and return 0/False/None.
    """

    # ---- queries -------------------------------------------------------------

    @abstractmethod
    def turn_number(self) -> int:
        """The current round, starting at 1. Increases each time the player gets a turn."""

    @abstractmethod
    def player(self) -> EntityView:
        """The player. During the player's own `on_death` hooks, `alive` is False."""

    @abstractmethod
    def entity(self, entity_id: int) -> EntityView | None:
        """The entity with this id, or None if it does not exist (e.g. already dead)."""

    @abstractmethod
    def entity_at(self, pos: Pos) -> EntityView | None:
        """The living entity standing on `pos`, or None."""

    @abstractmethod
    def entities(self, faction: str | None = None) -> list[EntityView]:
        """All living entities, optionally only one faction ("player" or "enemy"), by id."""

    @abstractmethod
    def entities_in_radius(
        self, center: Pos, radius: int, faction: str | None = None
    ) -> list[EntityView]:
        """Living entities within `radius` king-moves of `center` (inclusive), sorted by id.

        Includes an entity standing on `center` itself, such as the caster: filter it out
        if needed.
        """

    @abstractmethod
    def nearest_hostile(
        self, entity_id: int, max_distance: int, require_line_of_sight: bool = True
    ) -> EntityView | None:
        """The closest living entity of another faction within `max_distance`, or None.

        Ties are broken by lowest id.
        """

    @abstractmethod
    def is_wall(self, pos: Pos) -> bool:
        """True for walls and for tiles outside the map."""

    @abstractmethod
    def is_walkable(self, pos: Pos) -> bool:
        """True if `pos` is inside the map, not a wall and not occupied by a living entity."""

    @abstractmethod
    def line(self, start: Pos, end: Pos) -> list[Pos]:
        """Tiles on a straight line from `start` (excluded) to `end` (included).

        Walls are not skipped: stop at the first `ctx.is_wall` tile for projectiles.
        """

    @abstractmethod
    def has_line_of_sight(self, start: Pos, end: Pos) -> bool:
        """True if no wall lies strictly between the two tiles."""

    @abstractmethod
    def has_status(self, entity_id: int, status_id: str) -> bool:
        """True if the entity is alive and currently has the status."""

    @abstractmethod
    def random_int(self, low: int, high: int) -> int:
        """A seeded random integer with `low <= n <= high`. Never use other randomness."""

    @abstractmethod
    def chance(self, probability: float) -> bool:
        """True with the given probability (0.0 to 1.0), using the seeded RNG."""

    @abstractmethod
    def choice(self, options: Sequence[T]) -> T:
        """A seeded random element of a non-empty list or tuple."""

    # ---- actions -------------------------------------------------------------

    @abstractmethod
    def damage(self, target: int, amount: int, source: int | None = None) -> int:
        """Deal `amount` damage (floats are rounded) and return the HP actually removed.

        `source` is the entity responsible, if any. Reaching 0 HP kills the target and
        triggers its statuses' `on_death` hooks. Otherwise its `on_damaged` hooks run.
        """

    @abstractmethod
    def heal(self, target: int, amount: int) -> int:
        """Restore up to `amount` HP without exceeding max HP. Returns HP restored."""

    @abstractmethod
    def attack(self, attacker: int, target: int) -> int:
        """Melee attack: `attacker` deals its `attack` stat to an adjacent `target`.

        Returns damage dealt. Does nothing (returns 0) if they are not adjacent.
        """

    @abstractmethod
    def move(self, entity_id: int, pos: Pos) -> bool:
        """Step to an adjacent walkable tile. Returns True if the entity moved."""

    @abstractmethod
    def step_toward(self, entity_id: int, goal: Pos) -> bool:
        """Take one step along the shortest walkable path toward `goal`.

        The goal tile itself may be occupied (e.g. by the entity you are chasing). If other
        creatures block every path, it still steps closer when it can. Returns False if
        already adjacent to the goal or no step is possible.
        """

    @abstractmethod
    def teleport(self, entity_id: int, pos: Pos) -> bool:
        """Instantly move to any walkable tile on the map. Returns True on success."""

    @abstractmethod
    def push(self, entity_id: int, away_from: Pos, distance: int) -> int:
        """Knock an entity up to `distance` tiles directly away from `away_from`.

        Stops early at walls and other entities. Returns the number of tiles moved.
        Does nothing if the entity stands on `away_from`.
        """

    @abstractmethod
    def apply_status(
        self, target: int, status_id: str, duration: int | None, source: int | None = None
    ) -> bool:
        """Put a status on an entity for `duration` of ITS OWN turns (None = permanent).

        The status is ticked at the end of each of the holder's turns, not counting
        the turn in which it was applied, so `duration=3` affects the holder's next 3
        turns. Re-applying a status the entity already has keeps the longer duration
        and does not run `on_apply` again. Returns True if the target was alive.
        """

    @abstractmethod
    def remove_status(self, target: int, status_id: str) -> bool:
        """Remove a status immediately WITHOUT running `on_expire`. True if it was present."""

    @abstractmethod
    def spawn(self, monster_id: str, pos: Pos, faction: str = ENEMY_FACTION) -> int | None:
        """Create a monster on a walkable tile and return its id, or None if blocked.

        Use faction "player" to summon an ally. Spawned monsters act from the next round.
        """

    @abstractmethod
    def log(self, message: str) -> None:
        """Show a short message to the player (max 200 characters)."""


# ------------------------------------------------------------------ plugin globals

SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name)
    for name in (
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "int",
        "len",
        "list",
        "map",
        "max",
        "min",
        "range",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    )
}
"""The only builtins available to plugin code. No imports, no I/O, no introspection."""
