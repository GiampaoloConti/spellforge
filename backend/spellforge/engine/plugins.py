"""Loading plugin source code and keeping track of what each plugin defines.

A plugin is a single Python source file. It is executed with a namespace that holds
only the plugin API (`define_spell`, `define_status`, `define_monster`, `Pos`,
`DIRECTIONS`) and a small set of safe builtins. It declares content by calling the
`define_*` functions at top level.

WARNING: `load_plugin` executes code in this process. It is only for trusted,
hand-written plugins. Generated code must go through the sandbox instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from spellforge.engine.api import (
    SAFE_BUILTINS,
    DamagedHook,
    MonsterAct,
    MonsterDef,
    SpellCast,
    SpellDef,
    StatusDef,
    StatusHook,
    Target,
)
from spellforge.engine.geometry import DIRECTIONS, Pos

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class PluginLoadError(Exception):
    """The plugin source could not be loaded. The message is meant for the plugin author."""


@dataclass
class Plugin:
    id: str
    source: str
    spells: list[SpellDef] = field(default_factory=list)
    statuses: list[StatusDef] = field(default_factory=list)
    monsters: list[MonsterDef] = field(default_factory=list)


def _check_id(value: object, what: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise PluginLoadError(
            f"{what} id {value!r} must be snake_case: a lowercase letter followed by "
            "1-39 lowercase letters, digits or underscores"
        )
    return value


def _check_text(value: object, what: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise PluginLoadError(f"{what} must be a non-empty string of at most {max_len} chars")
    return value


def _check_int(value: object, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PluginLoadError(f"{what} must be an integer between {low} and {high}")
    return value


def _check_hook(value: object, what: str, required: bool = False) -> Any:
    if value is None and not required:
        return None
    if not callable(value):
        raise PluginLoadError(f"{what} must be a function{'' if required else ' or None'}")
    return value


def _make_namespace(plugin: Plugin) -> dict[str, Any]:
    def define_spell(
        *,
        id: str,
        name: str,
        description: str,
        mana_cost: int,
        target: str,
        on_cast: SpellCast,
        range: int = 0,
        cooldown: int = 0,
        requires_line_of_sight: bool = True,
    ) -> None:
        """Declare a spell the player can learn and cast.

        Args:
            id: unique snake_case id, e.g. "chain_lightning".
            name: display name, e.g. "Chain Lightning".
            description: one or two sentences shown to the player.
            mana_cost: mana spent per cast (0-50). The player has 10 max mana and
                regenerates 1 per turn.
            target: "self", "tile" or "entity" (see `Target`).
            on_cast: `def on_cast(ctx, caster, target)`: `caster` is the caster's entity
                id, `target` is the chosen `Pos` (the caster's own tile for "self").
                The engine has already checked range, line of sight and mana.
            range: max king-move distance to the target (ignored for "self").
            cooldown: player turns that must pass before casting it again (0 = none).
            requires_line_of_sight: whether walls may block the target.
        """
        try:
            target_kind = Target(target)
        except ValueError:
            raise PluginLoadError(
                f"spell target must be one of {[t.value for t in Target]}, got {target!r}"
            ) from None
        spell = SpellDef(
            id=_check_id(id, "spell"),
            name=_check_text(name, "spell name", 40),
            description=_check_text(description, "spell description", 300),
            mana_cost=_check_int(mana_cost, "mana_cost", 0, 50),
            cooldown=_check_int(cooldown, "cooldown", 0, 50),
            target=target_kind,
            range=0 if target_kind is Target.SELF else _check_int(range, "range", 1, 20),
            requires_line_of_sight=bool(requires_line_of_sight),
            on_cast=_check_hook(on_cast, "on_cast", required=True),
            plugin_id=plugin.id,
        )
        plugin.spells.append(spell)

    def define_status(
        *,
        id: str,
        name: str,
        description: str,
        prevents_action: bool = False,
        on_apply: StatusHook | None = None,
        on_turn: StatusHook | None = None,
        on_expire: StatusHook | None = None,
        on_damaged: DamagedHook | None = None,
        on_death: StatusHook | None = None,
    ) -> None:
        """Declare a status effect that can be put on entities with `ctx.apply_status`.

        Every hook receives `(ctx, status)` where `status` is a `StatusView`; use
        `status.holder` to get the affected entity's id. All hooks are optional.

        Args:
            id: unique snake_case id, e.g. "burning".
            name: display name.
            description: one sentence shown to the player.
            prevents_action: if True the holder skips its turns while affected
                (stun, freeze, sleep, polymorph...). Must be applied with a duration.
            on_apply: runs once when the status is first applied.
            on_turn: runs at the start of each of the holder's turns (e.g. damage over
                time), before the holder acts.
            on_expire: runs when the duration runs out, after the status is removed.
                Does not run if the holder dies or the status is removed early.
            on_damaged: `def on_damaged(ctx, status, amount, source)`: runs after the
                holder takes damage and survives. `source` is an entity id or None.
            on_death: runs when the holder dies, before it is removed from the map.
                `ctx.entity(status.holder)` still works and has `alive == False`.
        """
        status = StatusDef(
            id=_check_id(id, "status"),
            name=_check_text(name, "status name", 40),
            description=_check_text(description, "status description", 300),
            prevents_action=bool(prevents_action),
            on_apply=_check_hook(on_apply, "on_apply"),
            on_turn=_check_hook(on_turn, "on_turn"),
            on_expire=_check_hook(on_expire, "on_expire"),
            on_damaged=_check_hook(on_damaged, "on_damaged"),
            on_death=_check_hook(on_death, "on_death"),
            plugin_id=plugin.id,
        )
        plugin.statuses.append(status)

    def define_monster(
        *,
        id: str,
        name: str,
        description: str,
        glyph: str,
        max_hp: int,
        attack: int,
        act: MonsterAct | None = None,
    ) -> None:
        """Declare a monster that can appear in dungeons or be created with `ctx.spawn`.

        Args:
            id: unique snake_case id, e.g. "cave_troll".
            name: display name.
            description: one sentence shown to the player.
            glyph: a single printable character used to draw it, e.g. "T".
            max_hp: 1-100. For scale, the player has 20 HP and deals 3 melee damage.
            attack: melee damage per hit (0-20), used by `ctx.attack`.
            act: `def act(ctx, me)`: runs on each of the monster's turns; `me` is its
                entity id. Use it to move and attack. If omitted, the monster waits.
        """
        if not isinstance(glyph, str) or len(glyph) != 1 or not glyph.isprintable():
            raise PluginLoadError("glyph must be a single printable character")
        monster = MonsterDef(
            id=_check_id(id, "monster"),
            name=_check_text(name, "monster name", 40),
            description=_check_text(description, "monster description", 300),
            glyph=glyph,
            max_hp=_check_int(max_hp, "max_hp", 1, 100),
            attack=_check_int(attack, "attack", 0, 20),
            act=_check_hook(act, "act"),
            plugin_id=plugin.id,
        )
        plugin.monsters.append(monster)

    return {
        "__builtins__": dict(SAFE_BUILTINS),
        "__name__": f"spellforge_plugin_{plugin.id}",
        "define_spell": define_spell,
        "define_status": define_status,
        "define_monster": define_monster,
        "Pos": Pos,
        "DIRECTIONS": DIRECTIONS,
    }


PLUGIN_GLOBALS = ("define_spell", "define_status", "define_monster", "Pos", "DIRECTIONS")
"""Names a plugin can use besides `SAFE_BUILTINS`."""


def load_plugin(plugin_id: str, source: str) -> Plugin:
    """Execute trusted plugin source and collect its definitions. See module warning."""
    plugin = Plugin(id=_check_id(plugin_id, "plugin"), source=source)
    try:
        code = compile(source, f"<plugin {plugin_id}>", "exec")
    except SyntaxError as exc:
        raise PluginLoadError(f"syntax error on line {exc.lineno}: {exc.msg}") from exc
    try:
        exec(code, _make_namespace(plugin))
    except PluginLoadError:
        raise
    except Exception as exc:
        raise PluginLoadError(f"error while loading: {type(exc).__name__}: {exc}") from exc
    if not (plugin.spells or plugin.statuses or plugin.monsters):
        raise PluginLoadError("plugin defines nothing: call define_spell/status/monster")
    return plugin


class Registry:
    """All loaded content, indexed by id. Ids are global across plugins."""

    def __init__(self, plugins: list[Plugin] | None = None) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.spells: dict[str, SpellDef] = {}
        self.statuses: dict[str, StatusDef] = {}
        self.monsters: dict[str, MonsterDef] = {}
        for plugin in plugins or []:
            self.add(plugin)

    def add(self, plugin: Plugin) -> None:
        """Register a plugin. All-or-nothing: raises PluginLoadError on any id clash."""
        if plugin.id in self.plugins:
            raise PluginLoadError(f"a plugin named {plugin.id!r} is already loaded")
        tables: list[tuple[str, dict[str, Any], list[Any]]] = [
            ("spell", self.spells, plugin.spells),
            ("status", self.statuses, plugin.statuses),
            ("monster", self.monsters, plugin.monsters),
        ]
        for kind, table, defs in tables:
            ids = [d.id for d in defs]
            clashes = sorted({i for i in ids if i in table or ids.count(i) > 1})
            if clashes:
                raise PluginLoadError(f"{kind} id(s) already defined: {', '.join(clashes)}")
        self.plugins[plugin.id] = plugin
        for _, table, defs in tables:
            for d in defs:
                table[d.id] = d
