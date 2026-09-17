"""Checks a drafted spell before it reaches the player's game.

1. Static validation of the source.
2. Loading it in the sandbox (runs `define_*` validation).
3. Game rules the API can't express: exactly one spell, fresh ids, affordable mana cost.
4. Casting it in small test arenas, in the sandbox, and watching for crashes.

Everything runs synchronously (it starts a subprocess), so callers in async code should use
`asyncio.to_thread`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spellforge.engine import Cast, EventType, Game, InvalidAction, Plugin, PluginLoadError, Wait
from spellforge.engine.api import Target
from spellforge.engine.game import PLAYER_MAX_MANA, GameStatus
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
ROUNDS_AFTER_CAST = 3


@dataclass
class Verification:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spell_name: str = ""
    sprite_count: int = 0


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
        problems = _rule_problems(plugin, taken_ids)
        if problems:
            return Verification(ok=False, problems=problems)
        spell = plugin.spells[0]
        result = Verification(ok=True, spell_name=spell.name, sprite_count=len(plugin.sprites))
        try:
            for scenario, target in _scenarios(plugin):
                _run_scenario(plugin, scenario, target, result)
        except PluginLoadError as exc:  # e.g. an id clashing with a builtin
            result.problems.append(str(exc))
        result.ok = not result.problems
        return result
    finally:
        sandbox.close()


def _rule_problems(plugin: Plugin, taken_ids: dict[str, list[str]]) -> list[str]:
    problems = []
    if len(plugin.spells) != 1:
        problems.append(
            f"the plugin must define exactly one spell, it defines {len(plugin.spells)}"
        )
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
    for event in events:
        if event.type is EventType.PLUGIN_DISABLED:
            result.problems.append(f"test arena ({name}): crashed with {event.data['reason']}")
            return

    # Compare with a round where the player just waited: identical history means no effect.
    baseline_events = _arena(plugin).submit(Wait())
    cast_round = [e.to_dict() for e in cast_events if e.type is not EventType.SPELL_CAST]
    if cast_round == [e.to_dict() for e in baseline_events]:
        result.warnings.append(f"test arena ({name}): casting had no visible effect")
