"""Runs drafted plugins in the sandbox before they reach the player's game.

1. Static validation of the source.
2. Loading it in the sandbox (runs `define_*` validation).
3. Game rules the API can't express: exactly one spell (or a monster with a sprite), fresh
   ids, affordable mana cost.
4. Playing small test arenas in the sandbox and watching for crashes.

The result keeps the loaded definitions and every arena event, so the Tester agent can check
the plugin against its spec. Everything runs synchronously (it starts a subprocess), so async
callers should use `asyncio.to_thread`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache

from spellforge.agents.budget import PowerMeasurement, spell_limits
from spellforge.engine import (
    Cast,
    Event,
    EventType,
    Game,
    InvalidAction,
    Move,
    Plugin,
    PluginLoadError,
    Wait,
    load_plugin,
)
from spellforge.engine.api import MonsterDef, SpellDef, Target
from spellforge.engine.game import PLAYER_MAX_HP, PLAYER_MAX_MANA, GameStatus
from spellforge.engine.geometry import Pos
from spellforge.plugins import default_registry
from spellforge.sandbox.host import PluginSandbox
from spellforge.sandbox.validator import validate_source

ARENA = [
    "#############",
    "#...........#",
    "#.@g....g...#",
    "#....#......#",
    "#.......g...#",
    "#############",
]
MONSTER_ARENA = [
    "#############",
    "#...........#",
    "#.@....m....#",
    "#...........#",
    "#############",
]
PROBE_ARENA = [
    "##########################",
    "#........#...............#",
    "#.@.d....#...........d...#",
    "#........#...............#",
    "#...d....#.......d.......#",
    "#........................#",
    "#......d.................#",
    "##########################",
]
"""Training dummies near the caster, farther away, and far across the level behind a wall."""
PROBE_ROUNDS = 3
PROBE_START_HP = 2
DUMMY_SOURCE = """
define_monster(id="probe_dummy", name="training dummy", description="Stands still and takes it.",
               glyph="d", max_hp=12, attack=0)
"""
ROUNDS_AFTER_CAST = 3
MONSTER_ROUNDS = 6
MAX_MONSTER_DAMAGE = 14
"""A new monster may not take more than this from a full-health player who just waits."""


@dataclass
class Verification:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spell_name: str = ""
    sprite_count: int = 0
    balance_problems: list[str] = field(default_factory=list)
    """Problems measured by the balance probe (also included in `problems`)."""
    power: PowerMeasurement | None = None
    spell: SpellDef | None = None
    monster: MonsterDef | None = None
    player_id: int = 1
    monster_biggest_hit: int = 0
    """For monster plugins: the most damage the monster dealt in one hit in the arenas."""
    events: list[Event] = field(default_factory=list)
    """Everything that happened in the test arenas, for spec conformance checks."""


# ---- spells -----------------------------------------------------------------------------


def verify_spell_source(
    plugin_id: str, source: str, taken_ids: dict[str, list[str]]
) -> Verification:
    problems = [str(p) for p in validate_source(source)]
    if problems:
        return Verification(ok=False, problems=problems)
    try:
        sandbox, plugin = PluginSandbox.start(plugin_id, source)
    except PluginLoadError as exc:
        return Verification(ok=False, problems=[f"the plugin failed to load: {exc}"])
    try:
        problems = _id_problems(plugin, taken_ids) + _spell_rule_problems(plugin)
        if problems:
            return Verification(ok=False, problems=problems)
        spell = plugin.spells[0]
        result = Verification(
            ok=True, spell_name=spell.name, sprite_count=len(plugin.sprites), spell=spell
        )
        try:
            for scenario, target in _scenarios(plugin):
                _run_scenario(plugin, scenario, target, result)
            if not result.problems:
                result.power = probe_spell(plugin)
                limits = spell_limits(spell.mana_cost, spell.cooldown, spell.range)
                result.balance_problems = result.power.problems(
                    limits, spell.mana_cost, spell.cooldown
                )
                result.problems += result.balance_problems
        except PluginLoadError as exc:  # e.g. an id clashing with a builtin
            result.problems.append(str(exc))
        result.ok = not result.problems
        return result
    finally:
        sandbox.close()


@cache
def _dummy_plugin() -> Plugin:
    return load_plugin("probe_dummies", DUMMY_SOURCE)  # hand-written, trusted


def probe_spell(plugin: Plugin) -> PowerMeasurement:
    """Cast the spell once among training dummies and measure what it really does.

    The caster starts at 2 HP (so healing shows its true size) with full mana. Dummies neither
    move nor attack, so everything that happens is the spell's doing.
    """
    registry = default_registry()
    registry.add(plugin)
    registry.add(_dummy_plugin())
    spell = plugin.spells[0]
    game = Game.from_ascii(PROBE_ARENA, registry, {"d": "probe_dummy"}, spells=(spell.id,))
    caster = game.player
    caster.hp = PROBE_START_HP
    start = {e.id: e.pos for e in game.entities.values()}
    names = {e.id: e.name for e in game.entities.values()}

    in_reach = sorted(
        (
            e
            for e in game.entities.values()
            if e is not caster
            and e.pos.distance_to(caster.pos) <= spell.range
            and (not spell.requires_line_of_sight or game.map.has_line_of_sight(caster.pos, e.pos))
        ),
        key=lambda e: (e.pos.distance_to(caster.pos), e.id),
    )
    if spell.target is Target.SELF:
        target = None
    elif in_reach:
        target = in_reach[0].pos
    elif spell.target is Target.ENTITY:
        target = caster.pos
    else:
        target = next((p for p in caster.pos.neighbors() if game.is_walkable(p)), caster.pos)

    measurement = PowerMeasurement()
    try:
        events = game.submit(Cast(spell.id, target))
    except InvalidAction:
        return measurement
    for _ in range(PROBE_ROUNDS):
        if game.status is not GameStatus.PLAYING:
            break
        events += game.submit(Wait())

    player_side = {caster.id} | {
        e.data["entity"]
        for e in events
        if e.type is EventType.SPAWNED and e.data["faction"] == caster.faction
    }
    far: dict[int, int] = {}
    for event in events:
        data = event.data
        if event.type is EventType.SPAWNED and data["entity"] in player_side:
            monster = registry.monsters.get(data["kind"])
            measurement.ally_hp += monster.max_hp if monster else 0
            names[data["entity"]] = data["kind"]
        affected = None
        if event.type is EventType.DAMAGED and data["target"] not in player_side:
            if data["source"] in player_side:
                measurement.damage += data["amount"]
            affected = data["target"]
        elif event.type is EventType.HEALED and data["target"] in player_side:
            measurement.healing += data["amount"]
        elif event.type is EventType.TURN_SKIPPED and data["entity"] not in player_side:
            measurement.control += 1
        elif event.type is EventType.STATUS_APPLIED and data["entity"] not in player_side:
            affected = data["entity"]
        elif (
            event.type is EventType.MOVED
            and data["how"] != "step"
            and data["entity"] not in player_side
        ):
            affected = data["entity"]
        if affected is not None and affected in start:
            distance = start[affected].distance_to(start[caster.id])
            if distance > spell.range + 4:
                far[affected] = distance
    if far:
        measurement.farthest_reach = max(far.values())
        measurement.far_targets = [f"{names[i]} at {d} tiles" for i, d in sorted(far.items())]
    return measurement


def _id_problems(plugin: Plugin, taken_ids: dict[str, list[str]]) -> list[str]:
    problems = []
    kinds = {
        "spells": plugin.spells,
        "statuses": plugin.statuses,
        "monsters": plugin.monsters,
        "sprites": plugin.sprites,
    }
    for kind, defs in kinds.items():
        clashes = sorted({d.id for d in defs} & set(taken_ids.get(kind, [])))
        if clashes:
            problems.append(f"{kind} id(s) already taken: {', '.join(clashes)}; choose new ids")
    return problems


def _spell_rule_problems(plugin: Plugin) -> list[str]:
    problems = []
    if len(plugin.spells) != 1:
        problems.append(
            f"the plugin must define exactly one spell, it defines {len(plugin.spells)}"
        )
    for spell in plugin.spells:
        if not 1 <= spell.mana_cost <= PLAYER_MAX_MANA:
            problems.append(
                f"mana_cost {spell.mana_cost} is outside 1-{PLAYER_MAX_MANA} "
                f"(the player has {PLAYER_MAX_MANA} max mana)"
            )
    return problems


def _arena(plugin: Plugin) -> Game:
    registry = default_registry()
    registry.add(plugin)
    return Game.from_ascii(ARENA, registry, {"g": "goblin"}, spells=(plugin.spells[0].id,))


def _scenarios(plugin: Plugin) -> list[tuple[str, Pos | None]]:
    """Casts to try: the nearest enemy, the farthest one, and (for tile spells) empty floor."""
    spell = plugin.spells[0]
    if spell.target is Target.SELF:
        return [("cast on yourself", None)]
    game = _arena(plugin)
    me = game.player
    enemies = sorted(
        (e for e in game.entities.values() if e.faction != me.faction),
        key=lambda e: (e.pos.distance_to(me.pos), e.id),
    )
    in_range = [
        e.pos
        for e in enemies
        if e.pos.distance_to(me.pos) <= spell.range
        and (not spell.requires_line_of_sight or game.map.has_line_of_sight(me.pos, e.pos))
    ]
    scenarios: list[tuple[str, Pos | None]] = []
    if in_range:
        scenarios.append(("cast at the nearest goblin", in_range[0]))
        if len(in_range) > 1:
            scenarios.append(("cast at a farther goblin", in_range[-1]))
    if spell.target is Target.TILE:
        empty = me.pos + Pos(0, -1)
        if spell.range >= 1:
            scenarios.append(("cast at an empty floor tile", empty))
    if not scenarios:
        scenarios.append(("cast on your own tile", me.pos))
    return scenarios


def _run_scenario(plugin: Plugin, name: str, target: Pos | None, result: Verification) -> None:
    game = _arena(plugin)
    result.player_id = game.player.id
    spell = plugin.spells[0]
    try:
        cast_events = game.submit(Cast(spell.id, target))
    except InvalidAction as exc:
        result.problems.append(f"test arena ({name}): the cast was rejected: {exc}")
        return
    events = list(cast_events)
    for _ in range(ROUNDS_AFTER_CAST):
        if game.status is not GameStatus.PLAYING:
            break
        events += game.submit(Wait())
    result.events += events
    for event in events:
        if event.type is EventType.PLUGIN_DISABLED:
            result.problems.append(f"test arena ({name}): crashed with {event.data['reason']}")
            return

    # Compare with a round where the player just waited: identical history means no effect.
    baseline_events = _arena(plugin).submit(Wait())
    cast_round = [e.to_dict() for e in cast_events if e.type is not EventType.SPELL_CAST]
    if cast_round == [e.to_dict() for e in baseline_events]:
        result.warnings.append(f"test arena ({name}): casting had no visible effect")


# ---- monsters ---------------------------------------------------------------------------


def verify_monster_source(
    plugin_id: str, source: str, taken_ids: dict[str, list[str]]
) -> Verification:
    problems = [str(p) for p in validate_source(source)]
    if problems:
        return Verification(ok=False, problems=problems)
    try:
        sandbox, plugin = PluginSandbox.start(plugin_id, source)
    except PluginLoadError as exc:
        return Verification(ok=False, problems=[f"the plugin failed to load: {exc}"])
    try:
        problems = _id_problems(plugin, taken_ids)
        if plugin.spells:
            problems.append("a monster plugin must not define spells")
        if not plugin.monsters:
            problems.append("the plugin must define a monster with define_monster")
        elif plugin.monsters[0].sprite is None:
            problems.append("the monster needs a sprite: define_monster(sprite=...)")
        if problems:
            return Verification(ok=False, problems=problems)
        monster = plugin.monsters[0]
        result = Verification(
            ok=True, sprite_count=len(plugin.sprites), monster=monster, spell_name=monster.name
        )
        try:
            _monster_hunts(plugin, result)
            _monster_is_fought(plugin, result)
        except PluginLoadError as exc:
            result.problems.append(str(exc))
        result.ok = not result.problems
        return result
    finally:
        sandbox.close()


def _monster_arena(plugin: Plugin) -> Game:
    registry = default_registry()
    registry.add(plugin)
    return Game.from_ascii(
        MONSTER_ARENA,
        registry,
        {"m": plugin.monsters[0].id},
        spells=("firebolt", "frost_nova"),
    )


def _crashes(events: list[Event], name: str) -> list[str]:
    return [
        f"test arena ({name}): crashed with {e.data['reason']}"
        for e in events
        if e.type is EventType.PLUGIN_DISABLED
    ]


def _monster_hunts(plugin: Plugin, result: Verification) -> None:
    """The player waits while the monster acts: it must work, act, and not be overwhelming."""
    name = "the monster hunts a waiting player"
    game = _monster_arena(plugin)
    monster_id = next(e.id for e in game.entities.values() if e.kind == plugin.monsters[0].id)
    events: list[Event] = []
    for _ in range(MONSTER_ROUNDS):
        if game.status is not GameStatus.PLAYING:
            break
        events += game.submit(Wait())
    result.events += events
    result.problems += _crashes(events, name)
    _record_hits(result, events, monster_id)
    taken = PLAYER_MAX_HP - max(0, game.player.hp)
    if taken > MAX_MONSTER_DAMAGE:
        result.problems.append(
            f"test arena ({name}): it dealt {taken} damage in {MONSTER_ROUNDS} turns to a player "
            f"who never fought back (limit {MAX_MONSTER_DAMAGE}); it is too deadly"
        )
    if not any(_is_action_by(event, monster_id) for event in events):
        result.warnings.append(f"test arena ({name}): the monster never did anything")


def _record_hits(result: Verification, events: list[Event], monster_id: int) -> None:
    hits = [
        e.data["amount"]
        for e in events
        if e.type is EventType.DAMAGED and e.data.get("source") == monster_id
    ]
    result.monster_biggest_hit = max([result.monster_biggest_hit, *hits])


def _is_action_by(event: Event, entity_id: int) -> bool:
    data = event.data
    return (
        (event.type is EventType.MOVED and data.get("entity") == entity_id)
        or (event.type is EventType.ATTACKED and data.get("attacker") == entity_id)
        or (event.type is EventType.DAMAGED and data.get("source") == entity_id)
        or (event.type is EventType.HEALED)
        or (event.type in (EventType.STATUS_APPLIED, EventType.SPAWNED, EventType.MESSAGE))
    )


def _monster_is_fought(plugin: Plugin, result: Verification) -> None:
    """The player attacks with spells and melee, to exercise damage and death hooks."""
    name = "the player fights the monster"
    game = _monster_arena(plugin)
    monster_id = next(e.id for e in game.entities.values() if e.kind == plugin.monsters[0].id)
    events: list[Event] = []
    for _ in range(8):
        if game.status is not GameStatus.PLAYING:
            break
        foes = [e for e in game.entities.values() if e.faction != game.player.faction]
        if not foes:
            break
        foe = min(foes, key=lambda e: (e.pos.distance_to(game.player.pos), e.id))
        game.player.hp = PLAYER_MAX_HP  # keep the test about the monster's hooks, not survival
        actions = [
            Cast("firebolt", foe.pos),
            Cast("frost_nova"),
            Move(game.player.pos.direction_to(foe.pos)),
            Wait(),
        ]
        for action in actions:
            try:
                events += game.submit(action)
                break
            except InvalidAction:
                continue
    result.events += events
    result.problems += _crashes(events, name)
    _record_hits(result, events, monster_id)
