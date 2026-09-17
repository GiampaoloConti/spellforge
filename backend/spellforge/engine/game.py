"""The deterministic game engine: state, turn loop, combat and plugin hook dispatch.

Turn structure (one round):

1. Player turn start: round counter +1, statuses armed, `on_turn` hooks run. If a
   status prevents acting, the turn is skipped automatically.
2. The game waits for `Game.submit(action)`; the player acts.
3. Player turn end: armed statuses tick down and may expire; mana regenerates.
4. Every other entity, in id order: turn start, `act` hook (unless prevented), turn end.
5. Back to 1.

The dungeon is endless: killing the last enemy on a level opens stairs down, and stepping
onto them generates a deeper, harder level. The run ends only when the player dies.

Plugin failures never crash the game: any exception inside a hook disables the
plugin that owns it and emits a `PLUGIN_DISABLED` event.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any

from spellforge.engine.actions import Action, Cast, InvalidAction, Move, Wait
from spellforge.engine.api import ENEMY_FACTION, PLAYER_FACTION, PluginError, Target
from spellforge.engine.context import GameContext
from spellforge.engine.entity import Entity, StatusInstance
from spellforge.engine.events import Event, EventType
from spellforge.engine.gamemap import GameMap, GeneratedLevel, Tile, generate_level
from spellforge.engine.geometry import DIRECTIONS, Pos
from spellforge.engine.plugins import Plugin, Registry

PLAYER_MAX_HP = 20
PLAYER_ATTACK = 3
PLAYER_MAX_MANA = 10
MANA_REGEN_PER_TURN = 1
DESCEND_HEAL = 5

MAX_OPS_PER_TURN = 2_000
"""Ctx calls allowed during one entity's turn before the running plugin is disabled."""
MAX_HOOK_DEPTH = 12
"""Hooks triggering hooks (e.g. chained explosions) stop past this depth."""
MAX_ENTITIES = 200
MAX_SKIPPED_PLAYER_TURNS = 50


class GameStatus(StrEnum):
    PLAYING = "playing"
    LOST = "lost"


EncounterTable = Callable[[int], Sequence[tuple[str, int]]]
"""Given a depth, the monster ids that may appear there with their relative weights."""


def goblins_only(depth: int) -> Sequence[tuple[str, int]]:
    return [("goblin", 1)]


def monsters_per_room(depth: int) -> tuple[int, int]:
    """(min, max) monsters in each room at this depth."""
    return 1 + (depth - 1) // 3, min(5, 2 + (depth - 1) // 2)


class BudgetExceeded(PluginError):
    """A plugin used more ctx calls in one turn than `MAX_OPS_PER_TURN` allows."""


class Game:
    def __init__(
        self,
        game_map: GameMap,
        registry: Registry,
        seed: int,
        player_pos: Pos,
        encounters: EncounterTable = goblins_only,
    ) -> None:
        self.map = game_map
        self.registry = registry
        self.seed = seed
        self.encounters = encounters
        self.rng = random.Random(seed)
        self.depth = 1
        self.stairs: Pos | None = None
        self.turn = 0
        self.status = GameStatus.PLAYING
        self.history: list[Event] = []
        self.entities: dict[int, Entity] = {}
        self.spellbook: list[str] = []
        self.spell_ready_turn: dict[str, int] = {}
        self.disabled_plugins: dict[str, str] = {}
        self.ctx = GameContext(self)

        self._next_id = 1
        self._started = False
        self._ops = 0
        self._hook_depth = 0
        self._active_plugins: list[str] = []
        self._budget_culprit: str | None = None
        self._descend_pending = False

        if self.map.is_wall(player_pos):
            raise ValueError(f"player start {player_pos} is a wall")
        self.player = self._add_entity(
            kind="player",
            name="you",
            glyph="@",
            faction=PLAYER_FACTION,
            pos=player_pos,
            max_hp=PLAYER_MAX_HP,
            attack=PLAYER_ATTACK,
            max_mana=PLAYER_MAX_MANA,
        )

    # ------------------------------------------------------------------ setup

    @classmethod
    def new(
        cls,
        seed: int,
        registry: Registry,
        spells: tuple[str, ...] = (),
        encounters: EncounterTable = goblins_only,
    ) -> Game:
        """A generated dungeon, starting at depth 1, with monsters in every room but the first."""
        rng = random.Random(seed)
        level = generate_level(rng)
        game = cls(level.map, registry, seed, level.rooms[0].center, encounters)
        game._populate(level, rng)
        for spell_id in spells:
            game.learn_spell(spell_id)
        game.start()
        return game

    @classmethod
    def from_ascii(
        cls,
        rows: list[str],
        registry: Registry,
        legend: dict[str, str] | None = None,
        seed: int = 0,
        spells: tuple[str, ...] = (),
        encounters: EncounterTable = goblins_only,
    ) -> Game:
        """Build a game from an ASCII map: `@` is the player, `legend` maps chars to monsters.

        Monster characters are lowercase for enemies and uppercase for allies.
        """
        game_map, markers = GameMap.from_ascii(rows)
        if len(markers.get("@", [])) != 1:
            raise ValueError("map needs exactly one '@'")
        game = cls(game_map, registry, seed, markers.pop("@")[0], encounters)
        legend = legend or {}
        placements = sorted((pos.y, pos.x, ch) for ch, ps in markers.items() for pos in ps)
        for y, x, ch in placements:
            if ch.lower() not in legend:
                raise ValueError(f"no legend entry for map character {ch!r}")
            faction = ENEMY_FACTION if ch.islower() else PLAYER_FACTION
            game.add_monster(legend[ch.lower()], Pos(x, y), faction)
        for spell_id in spells:
            game.learn_spell(spell_id)
        game.start()
        return game

    def start(self) -> list[Event]:
        """Begin the first player turn. Called by the constructors above."""
        if self._started:
            raise RuntimeError("game already started")
        self._started = True
        return self._collect(self._begin_player_turn)

    def add_monster(self, monster_id: str, pos: Pos, faction: str = ENEMY_FACTION) -> Entity:
        mdef = self.registry.monsters[monster_id]
        if not self.is_walkable(pos):
            raise ValueError(f"cannot place {monster_id} on {pos}")
        return self._add_entity(
            kind=mdef.id,
            name=mdef.name,
            glyph=mdef.glyph,
            faction=faction,
            pos=pos,
            max_hp=mdef.max_hp,
            attack=mdef.attack,
        )

    def load_plugin(self, plugin: Plugin) -> None:
        """Hot-load a plugin into the running game."""
        self.registry.add(plugin)

    def learn_spell(self, spell_id: str) -> None:
        if spell_id not in self.registry.spells:
            raise ValueError(f"unknown spell {spell_id!r}")
        if spell_id not in self.spellbook:
            self.spellbook.append(spell_id)

    # ------------------------------------------------------------ player input

    def submit(self, action: Action) -> list[Event]:
        """Perform the player's action and run the world until the player's next turn.

        Returns the events that happened. Raises `InvalidAction` (without changing any
        state) if the action is not allowed.
        """
        if not self._started:
            raise RuntimeError("call start() first")
        if self.status is not GameStatus.PLAYING:
            raise InvalidAction("the game is over")
        if isinstance(action, Move):
            perform = self._prepare_move(action)
        elif isinstance(action, Cast):
            perform = self._prepare_cast(action)
        elif isinstance(action, Wait):
            perform = lambda: None  # noqa: E731
        else:
            raise InvalidAction(f"unknown action {action!r}")

        def run_round() -> None:
            self._ops = 0
            perform()
            self._end_turn(self.player)
            if self._descend_pending and self.status is GameStatus.PLAYING:
                self._descend()
            else:
                self._run_other_entities()
            self._begin_player_turn()

        return self._collect(run_round)

    def _prepare_move(self, action: Move) -> Callable[[], None]:
        if action.direction not in DIRECTIONS:
            raise InvalidAction("direction must be a unit step")
        dest = self.player.pos + action.direction
        occupant = self.living_entity_at(dest)
        if occupant is not None:
            if occupant.faction == self.player.faction:
                raise InvalidAction(f"{occupant.name} is in the way")
            return lambda: self.melee(self.player, occupant)
        if self.map.is_wall(dest):
            raise InvalidAction("a wall blocks the way")

        def step() -> None:
            self.move_entity(self.player, dest, "step")
            self._descend_pending = self.map.is_stairs(dest)

        return step

    def _prepare_cast(self, action: Cast) -> Callable[[], None]:
        spell = self.registry.spells.get(action.spell_id)
        if spell is None or action.spell_id not in self.spellbook:
            raise InvalidAction(f"you don't know the spell {action.spell_id!r}")
        if spell.plugin_id in self.disabled_plugins:
            raise InvalidAction(f"{spell.name} is disabled")
        if self.player.mana < spell.mana_cost:
            raise InvalidAction(f"not enough mana for {spell.name}")
        if self.spell_cooldown(spell.id) > 0:
            raise InvalidAction(f"{spell.name} is on cooldown")
        origin = self.player.pos
        if spell.target is Target.SELF:
            target = origin
        else:
            if action.target is None:
                raise InvalidAction(f"{spell.name} needs a target")
            target = action.target
            if not self.map.in_bounds(target) or self.map.is_wall(target):
                raise InvalidAction("invalid target tile")
            if origin.distance_to(target) > spell.range:
                raise InvalidAction("target is out of range")
            if spell.requires_line_of_sight and not self.map.has_line_of_sight(origin, target):
                raise InvalidAction("no line of sight to target")
            if spell.target is Target.ENTITY and self.living_entity_at(target) is None:
                raise InvalidAction("there is no creature there")

        def perform() -> None:
            self.player.mana -= spell.mana_cost
            self.spell_ready_turn[spell.id] = self.turn + spell.cooldown + 1
            self.emit(
                EventType.SPELL_CAST,
                caster=self.player.id,
                spell=spell.id,
                target=[target.x, target.y],
            )
            self.call_hook(spell.plugin_id, spell.on_cast, self.player.id, target)

        return perform

    def spell_cooldown(self, spell_id: str) -> int:
        """Player turns left until the spell can be cast again (0 = ready)."""
        return max(0, self.spell_ready_turn.get(spell_id, 0) - self.turn)

    # -------------------------------------------------------------- turn loop

    def _begin_player_turn(self) -> None:
        skipped = 0
        while self.status is GameStatus.PLAYING:
            self.turn += 1
            self._ops = 0
            self._start_turn(self.player)
            if self.status is not GameStatus.PLAYING:
                return
            if self.can_act(self.player) or skipped >= MAX_SKIPPED_PLAYER_TURNS:
                return
            skipped += 1
            self.emit(EventType.TURN_SKIPPED, entity=self.player.id)
            self._end_turn(self.player)
            self._run_other_entities()

    def _run_other_entities(self) -> None:
        for entity_id in [i for i in self.entities if i != self.player.id]:
            if self.status is not GameStatus.PLAYING:
                return
            entity = self.entities.get(entity_id)
            if entity is None or not entity.alive:
                continue
            self._ops = 0
            self._start_turn(entity)
            if not entity.alive or self.status is not GameStatus.PLAYING:
                continue
            if not self.can_act(entity):
                self.emit(EventType.TURN_SKIPPED, entity=entity.id)
            else:
                mdef = self.registry.monsters.get(entity.kind)
                if mdef is not None and mdef.act is not None:
                    self.call_hook(mdef.plugin_id, mdef.act, entity.id)
            self._end_turn(entity)

    def _start_turn(self, entity: Entity) -> None:
        instances = list(entity.statuses.values())
        for inst in instances:
            inst.armed = True
        for inst in instances:
            if not entity.alive or self.status is not GameStatus.PLAYING:
                return
            if entity.statuses.get(inst.status_id) is inst:
                self._run_status_hook(entity, inst, "on_turn")

    def _end_turn(self, entity: Entity) -> None:
        for inst in list(entity.statuses.values()):
            if not entity.alive or self.status is not GameStatus.PLAYING:
                return
            if entity.statuses.get(inst.status_id) is not inst:
                continue
            if not inst.armed or inst.remaining is None:
                continue
            inst.remaining -= 1
            if inst.remaining <= 0:
                del entity.statuses[inst.status_id]
                self.emit(EventType.STATUS_EXPIRED, entity=entity.id, status=inst.status_id)
                self._run_status_hook(entity, inst, "on_expire")
        if entity is self.player and entity.alive:
            entity.mana = min(entity.max_mana, entity.mana + MANA_REGEN_PER_TURN)

    def can_act(self, entity: Entity) -> bool:
        return not any(self.registry.statuses[s].prevents_action for s in entity.statuses)

    # ------------------------------------------------------------ world rules

    def living_entity_at(self, pos: Pos) -> Entity | None:
        for entity in self.entities.values():
            if entity.alive and entity.pos == pos:
                return entity
        return None

    def is_walkable(self, pos: Pos) -> bool:
        return not self.map.is_wall(pos) and self.living_entity_at(pos) is None

    def move_entity(self, entity: Entity, pos: Pos, how: str) -> None:
        old = entity.pos
        entity.pos = pos
        self.emit(
            EventType.MOVED,
            entity=entity.id,
            how=how,
            **{"from": [old.x, old.y]},
            to=[pos.x, pos.y],
        )

    def first_step_toward(self, start: Pos, goal: Pos) -> Pos | None:
        """First tile of a shortest 8-way path to `goal` (which may be occupied), or None.

        Among equally short paths, prefers the step closest to the goal in a straight line,
        so creatures walk the way a player would expect. If other creatures block every
        path, falls back to the walls-only path so creatures queue up instead of freezing.
        """
        if start.distance_to(goal) <= 1 or self.map.is_wall(goal):
            return None
        for creatures_block in (True, False):
            dist = self._distances_from(goal, start, creatures_block)
            if start not in dist:
                continue
            best = dist[start] - 1
            steps = [p for p in start.neighbors() if dist.get(p) == best and self.is_walkable(p)]
            if steps:
                return min(steps, key=lambda p: (p.x - goal.x) ** 2 + (p.y - goal.y) ** 2)
        return None

    def _distances_from(self, goal: Pos, start: Pos, creatures_block: bool) -> dict[Pos, int]:
        """Breadth-first step counts flowing out from `goal`, stopping once `start` is reached."""
        passable = self.is_walkable if creatures_block else (lambda p: not self.map.is_wall(p))
        dist: dict[Pos, int] = {goal: 0}
        queue = deque([goal])
        while queue and start not in dist:
            current = queue.popleft()
            for nxt in current.neighbors():
                if nxt not in dist and (nxt == start or passable(nxt)):
                    dist[nxt] = dist[current] + 1
                    queue.append(nxt)
        return dist

    def melee(self, attacker: Entity, target: Entity) -> int:
        self.emit(EventType.ATTACKED, attacker=attacker.id, target=target.id)
        return self.damage(target, attacker.attack, attacker.id)

    def damage(self, target: Entity, amount: int, source: int | None) -> int:
        if not target.alive or amount <= 0:
            return 0
        dealt = min(amount, target.hp)
        target.hp -= dealt
        self.emit(
            EventType.DAMAGED,
            target=target.id,
            pos=[target.pos.x, target.pos.y],
            amount=dealt,
            source=source,
            hp=target.hp,
        )
        if target.hp <= 0:
            self.kill(target)
            return dealt
        for inst in list(target.statuses.values()):
            if not target.alive:
                break
            if target.statuses.get(inst.status_id) is inst:
                self._run_status_hook(target, inst, "on_damaged", dealt, source)
        return dealt

    def heal(self, target: Entity, amount: int) -> int:
        if not target.alive or amount <= 0:
            return 0
        restored = min(amount, target.max_hp - target.hp)
        if restored > 0:
            target.hp += restored
            self.emit(
                EventType.HEALED,
                target=target.id,
                pos=[target.pos.x, target.pos.y],
                amount=restored,
                hp=target.hp,
            )
        return restored

    def kill(self, entity: Entity) -> None:
        if not entity.alive:
            return
        entity.alive = False
        entity.hp = 0
        self.emit(EventType.DIED, entity=entity.id, pos=[entity.pos.x, entity.pos.y])
        for inst in list(entity.statuses.values()):
            self._run_status_hook(entity, inst, "on_death")
        entity.statuses.clear()
        del self.entities[entity.id]
        if self.status is not GameStatus.PLAYING:
            return
        if entity is self.player:
            self._end_game(GameStatus.LOST)
        elif self.stairs is None and not any(
            e.alive and e.faction == ENEMY_FACTION for e in self.entities.values()
        ):
            self._open_stairs()

    # ------------------------------------------------------------- levels

    def _populate(self, level: GeneratedLevel, rng: random.Random) -> None:
        table = [
            (monster_id, weight)
            for monster_id, weight in self.encounters(self.depth)
            if monster_id in self.registry.monsters and weight > 0
        ]
        if not table:
            return
        ids = [monster_id for monster_id, _ in table]
        weights = [weight for _, weight in table]
        low, high = monsters_per_room(self.depth)
        for room in level.rooms[1:]:
            free = room.floor_tiles()
            for _ in range(min(len(free), rng.randint(low, high))):
                pos = free.pop(rng.randrange(len(free)))
                self.add_monster(rng.choices(ids, weights)[0], pos)

    def _open_stairs(self) -> None:
        """Put stairs down on the reachable floor tile farthest from the player."""
        start = self.player.pos
        distance = {start: 0}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in current.neighbors():
                if nxt not in distance and not self.map.is_wall(nxt):
                    distance[nxt] = distance[current] + 1
                    queue.append(nxt)
        stairs = max(distance, key=lambda p: (distance[p], -p.y, -p.x))
        self.map.set(stairs, Tile.STAIRS)
        self.stairs = stairs
        self.emit(EventType.LEVEL_CLEARED, depth=self.depth, stairs=[stairs.x, stairs.y])

    def _descend(self) -> None:
        self._descend_pending = False
        self.depth += 1
        rng = random.Random(self.seed * 7919 + self.depth)
        level = generate_level(rng)
        for entity in [e for e in self.entities.values() if e is not self.player]:
            entity.alive = False
            del self.entities[entity.id]
        self.map = level.map
        self.stairs = None
        self.player.pos = level.rooms[0].center
        self.player.hp = min(self.player.max_hp, self.player.hp + DESCEND_HEAL)
        self.player.mana = self.player.max_mana
        self._populate(level, rng)
        self.emit(EventType.LEVEL_STARTED, depth=self.depth)

    def apply_status(
        self, target: Entity, status_id: str, duration: int | None, source: int | None
    ) -> bool:
        sdef = self.registry.statuses[status_id]
        if not target.alive or sdef.plugin_id in self.disabled_plugins:
            return False
        existing = target.statuses.get(status_id)
        if existing is not None:
            if existing.remaining is not None and (
                duration is None or duration > existing.remaining
            ):
                existing.remaining = duration
                existing.armed = False  # a fresh duration starts counting next turn
            self.emit(
                EventType.STATUS_APPLIED,
                entity=target.id,
                status=status_id,
                remaining=existing.remaining,
                refreshed=True,
            )
            return True
        inst = StatusInstance(status_id, duration, source)
        target.statuses[status_id] = inst
        self.emit(
            EventType.STATUS_APPLIED,
            entity=target.id,
            status=status_id,
            remaining=duration,
            refreshed=False,
        )
        self._run_status_hook(target, inst, "on_apply")
        return True

    def remove_status(self, target: Entity, status_id: str) -> bool:
        if target.statuses.pop(status_id, None) is None:
            return False
        self.emit(EventType.STATUS_REMOVED, entity=target.id, status=status_id)
        return True

    def spawn(self, monster_id: str, pos: Pos, faction: str) -> Entity | None:
        mdef = self.registry.monsters[monster_id]
        if (
            mdef.plugin_id in self.disabled_plugins
            or len(self.entities) >= MAX_ENTITIES
            or not self.is_walkable(pos)
        ):
            return None
        entity = self.add_monster(monster_id, pos, faction)
        self.emit(
            EventType.SPAWNED,
            entity=entity.id,
            kind=monster_id,
            pos=[pos.x, pos.y],
            faction=faction,
        )
        return entity

    def _add_entity(
        self,
        *,
        kind: str,
        name: str,
        glyph: str,
        faction: str,
        pos: Pos,
        max_hp: int,
        attack: int,
        max_mana: int = 0,
    ) -> Entity:
        entity = Entity(
            id=self._next_id,
            kind=kind,
            name=name,
            glyph=glyph,
            faction=faction,
            pos=pos,
            hp=max_hp,
            max_hp=max_hp,
            attack=attack,
            mana=max_mana,
            max_mana=max_mana,
        )
        self._next_id += 1
        self.entities[entity.id] = entity
        return entity

    def _end_game(self, result: GameStatus) -> None:
        self.status = result
        self.emit(EventType.GAME_OVER, result=result.value, depth=self.depth)

    # ------------------------------------------------------------ plugin hooks

    def call_hook(self, plugin_id: str, hook: Callable[..., Any], *args: Any) -> None:
        """Run plugin code; on any failure, disable the plugin instead of crashing."""
        if plugin_id in self.disabled_plugins:
            return
        if self._hook_depth >= MAX_HOOK_DEPTH:
            self.emit(EventType.MESSAGE, text="The magic fizzles: too many chained effects.")
            return
        self._hook_depth += 1
        self._active_plugins.append(plugin_id)
        try:
            hook(self.ctx, *args)
            if self._budget_culprit is not None:
                raise BudgetExceeded("the hook swallowed an action budget error")
        except Exception as exc:
            if self._budget_culprit is None:
                self.disable_plugin(plugin_id, exc)
            else:
                # Blame the plugin that blew the budget, and abort every hook up the chain.
                self.disable_plugin(self._budget_culprit, exc)
                if self._hook_depth > 1:
                    raise
                self._budget_culprit = None
                self._ops = 0
        finally:
            self._active_plugins.pop()
            self._hook_depth -= 1

    def count_op(self) -> None:
        """Called by the context on every plugin API call."""
        if self._budget_culprit is not None:
            raise BudgetExceeded("action budget exceeded")
        self._ops += 1
        if self._ops > MAX_OPS_PER_TURN:
            self._budget_culprit = self._active_plugins[-1] if self._active_plugins else "unknown"
            raise BudgetExceeded(f"more than {MAX_OPS_PER_TURN} API calls in one turn")

    def disable_plugin(self, plugin_id: str, error: Exception) -> None:
        if plugin_id in self.disabled_plugins or plugin_id not in self.registry.plugins:
            return
        # Errors relayed from a sandboxed plugin already carry their original type in `reason`.
        reason = getattr(error, "reason", None) or f"{type(error).__name__}: {error}"
        self.disabled_plugins[plugin_id] = reason
        self.emit(EventType.PLUGIN_DISABLED, plugin=plugin_id, reason=reason)
        owned = {s.id for s in self.registry.plugins[plugin_id].statuses}
        for entity in list(self.entities.values()):
            for status_id in [s for s in entity.statuses if s in owned]:
                self.remove_status(entity, status_id)

    def _run_status_hook(
        self, entity: Entity, inst: StatusInstance, hook_name: str, *extra: Any
    ) -> None:
        sdef = self.registry.statuses[inst.status_id]
        hook = getattr(sdef, hook_name)
        if hook is not None:
            self.call_hook(sdef.plugin_id, hook, inst.view(entity.id), *extra)

    # ------------------------------------------------------------ output

    def emit(self, event_type: EventType, **data: Any) -> None:
        self.history.append(Event(event_type, self.turn, data))

    def _collect(self, run: Callable[[], None]) -> list[Event]:
        start = len(self.history)
        run()
        return self.history[start:]

    def appearance(self, entity: Entity) -> str | None:
        """The sprite id to draw an entity with, or None for the client's default art."""
        for status_id in reversed(list(entity.statuses)):
            sprite = self.registry.statuses[status_id].appearance
            if sprite is not None and sprite in self.registry.sprites:
                return sprite
        monster = self.registry.monsters.get(entity.kind)
        if monster is not None and monster.sprite in self.registry.sprites:
            return monster.sprite
        return None

    def sprite_art(self, sprite_ids: set[str] | None = None) -> dict[str, Any]:
        """Pixel art for sprites defined by plugins (all of them, or just `sprite_ids`)."""
        return {
            sprite.id: {"palette": dict(sprite.palette), "rows": list(sprite.rows)}
            for sprite in self.registry.sprites.values()
            if sprite_ids is None or sprite.id in sprite_ids
        }

    def snapshot(self) -> dict[str, Any]:
        """The full visible state as JSON-ready data (used by clients and determinism tests)."""
        return {
            "seed": self.seed,
            "player_id": self.player.id,
            "depth": self.depth,
            "turn": self.turn,
            "status": self.status.value,
            "map": self.map.to_ascii(),
            "entities": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "name": e.name,
                    "glyph": e.glyph,
                    "faction": e.faction,
                    "pos": [e.pos.x, e.pos.y],
                    "hp": e.hp,
                    "max_hp": e.max_hp,
                    "mana": e.mana,
                    "max_mana": e.max_mana,
                    "attack": e.attack,
                    "appearance": self.appearance(e),
                    "can_act": self.can_act(e),
                    "statuses": [
                        {"id": s.status_id, "remaining": s.remaining} for s in e.statuses.values()
                    ],
                }
                for e in self.entities.values()
            ],
            "spells": [
                {
                    "id": spell.id,
                    "name": spell.name,
                    "description": spell.description,
                    "mana_cost": spell.mana_cost,
                    "target": spell.target.value,
                    "range": spell.range,
                    "requires_line_of_sight": spell.requires_line_of_sight,
                    "cooldown_remaining": self.spell_cooldown(spell.id),
                    "disabled": spell.plugin_id in self.disabled_plugins,
                }
                for spell in (self.registry.spells[s] for s in self.spellbook)
            ],
            "disabled_plugins": dict(self.disabled_plugins),
        }
