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
    MAX_SPRITE_COLORS,
    SAFE_BUILTINS,
    SPRITE_SIZE,
    DamagedHook,
    MonsterAct,
    MonsterDef,
    SpellCast,
    SpellDef,
    SpriteDef,
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
    sprites: list[SpriteDef] = field(default_factory=list)


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


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _normalize_rows(rows: object) -> list[str]:
    """Forgive small counting slips in hand-typed (or LLM-typed) pixel art.

    Short rows are padded with transparent pixels, transparent overflow is trimmed and missing
    rows are added at the top (so feet stay on the ground). Art that would lose visible pixels
    is still rejected.
    """
    if not isinstance(rows, list | tuple) or not all(isinstance(r, str) for r in rows):
        raise PluginLoadError(f"sprite rows must be a list of {SPRITE_SIZE} strings")
    fixed: list[str] = []
    for y, row in enumerate(rows):
        if len(row) > SPRITE_SIZE:
            overflow = len(row) - SPRITE_SIZE
            if row.endswith("." * overflow):
                row = row[:SPRITE_SIZE]
            elif row.startswith("." * overflow):
                row = row[overflow:]
            else:
                raise PluginLoadError(
                    f"sprite row {y} has {len(row)} characters; rows must be {SPRITE_SIZE} wide"
                )
        fixed.append(row.ljust(SPRITE_SIZE, "."))
    while len(fixed) > SPRITE_SIZE and set(fixed[-1]) == {"."}:
        fixed.pop()
    while len(fixed) > SPRITE_SIZE and set(fixed[0]) == {"."}:
        fixed.pop(0)
    if len(fixed) > SPRITE_SIZE:
        raise PluginLoadError(f"sprite has {len(fixed)} rows; it must be {SPRITE_SIZE} tall")
    return ["." * SPRITE_SIZE] * (SPRITE_SIZE - len(fixed)) + fixed


def _check_sprite_ref(value: object, what: str) -> str | None:
    if value is None:
        return None
    return _check_id(value, what)


def normalize_sprite(palette: object, rows: object) -> tuple[dict[str, str], list[str]]:
    """Validate pixel art and return it normalized. Raises PluginLoadError explaining why not."""
    if not isinstance(palette, dict):
        raise PluginLoadError("sprite palette must be a dict of characters to colors")
    palette = {key: color for key, color in palette.items() if key != "."}  # always clear
    if not 1 <= len(palette) <= MAX_SPRITE_COLORS:
        raise PluginLoadError(f"sprite palette must have 1-{MAX_SPRITE_COLORS} colors")
    for key, color in palette.items():
        if not isinstance(key, str) or len(key) != 1 or not key.isprintable():
            raise PluginLoadError(f"palette key {key!r} must be one printable character")
        if not isinstance(color, str) or not HEX_COLOR.match(color):
            raise PluginLoadError(f"palette color {color!r} must look like '#1a2b3c'")
    fixed = _normalize_rows(rows)
    for y, row in enumerate(fixed):
        unknown = sorted({ch for ch in row if ch != "." and ch not in palette})
        if unknown:
            raise PluginLoadError(f"sprite row {y} uses colors missing from the palette: {unknown}")
    if all(ch == "." for row in fixed for ch in row):
        raise PluginLoadError("sprite is completely transparent")
    return {str(k): str(v).lower() for k, v in palette.items()}, fixed


def _check_hook(value: object, what: str, required: bool = False) -> Any:
    if value is None and not required:
        return None
    if not callable(value):
        raise PluginLoadError(f"{what} must be a function{'' if required else ' or None'}")
    return value


def make_namespace(plugin: Plugin) -> dict[str, Any]:
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
        appearance: str | None = None,
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
            appearance: id of a sprite (see `define_sprite`) to draw the holder with
                while the status lasts. Use it whenever the effect changes how a creature
                looks: turned to stone, polymorphed into a sheep, wrapped in vines... The
                most recently applied status with an appearance wins.
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
            appearance=_check_sprite_ref(appearance, "appearance sprite"),
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
        sprite: str | None = None,
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
            sprite: id of a sprite (see `define_sprite`) to draw it with. Without one,
                the glyph is drawn instead.
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
            sprite=_check_sprite_ref(sprite, "sprite"),
            plugin_id=plugin.id,
        )
        plugin.monsters.append(monster)

    def define_sprite(*, id: str, palette: dict[str, str], rows: list[str]) -> None:
        """Declare 16x16 pixel art for creatures, used by `define_monster(sprite=...)` and
        `define_status(appearance=...)`.

        Args:
            id: unique snake_case id, e.g. "stone_statue".
            palette: maps single characters to colors, e.g. {"k": "#140d1c", "g": "#5caa3c"}.
                At most 16 colors. "." is reserved for transparent pixels.
            rows: exactly 16 strings of exactly 16 characters, top row first. Each
                character is a palette key or "." (transparent).

        How to draw a good sprite: face right; fill most of the 16x16 box, feet on the
        bottom rows; give the shape a 1-pixel dark outline ("#140d1c") so it reads on the
        dark dungeon floor; use 3-6 colors with a lighter highlight on the top-left and a
        darker shade on the bottom-right.
        """
        sprite_id = _check_id(id, "sprite")
        palette, rows = normalize_sprite(palette, rows)
        plugin.sprites.append(
            SpriteDef(
                id=sprite_id,
                palette=palette,
                rows=tuple(rows),
                plugin_id=plugin.id,
            )
        )

    return {
        "__builtins__": dict(SAFE_BUILTINS),
        "__name__": f"spellforge_plugin_{plugin.id}",
        "define_spell": define_spell,
        "define_status": define_status,
        "define_monster": define_monster,
        "define_sprite": define_sprite,
        "Pos": Pos,
        "DIRECTIONS": DIRECTIONS,
    }


PLUGIN_GLOBALS = (
    "define_spell",
    "define_status",
    "define_monster",
    "define_sprite",
    "Pos",
    "DIRECTIONS",
)
"""Names a plugin can use besides `SAFE_BUILTINS`."""


def load_plugin(plugin_id: str, source: str) -> Plugin:
    """Execute trusted plugin source and collect its definitions. See module warning."""
    plugin = Plugin(id=_check_id(plugin_id, "plugin"), source=source)
    try:
        code = compile(source, f"<plugin {plugin_id}>", "exec")
    except SyntaxError as exc:
        raise PluginLoadError(f"syntax error on line {exc.lineno}: {exc.msg}") from exc
    try:
        exec(code, make_namespace(plugin))
    except PluginLoadError:
        raise
    except Exception as exc:
        raise PluginLoadError(f"error while loading: {type(exc).__name__}: {exc}") from exc
    if not (plugin.spells or plugin.statuses or plugin.monsters or plugin.sprites):
        raise PluginLoadError("plugin defines nothing: call define_spell/status/monster/sprite")
    return plugin


class Registry:
    """All loaded content, indexed by id. Ids are global across plugins."""

    def __init__(self, plugins: list[Plugin] | None = None) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.spells: dict[str, SpellDef] = {}
        self.statuses: dict[str, StatusDef] = {}
        self.monsters: dict[str, MonsterDef] = {}
        self.sprites: dict[str, SpriteDef] = {}
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
            ("sprite", self.sprites, plugin.sprites),
        ]
        for kind, table, defs in tables:
            ids = [d.id for d in defs]
            clashes = sorted({i for i in ids if i in table or ids.count(i) > 1})
            if clashes:
                raise PluginLoadError(f"{kind} id(s) already defined: {', '.join(clashes)}")
        known_sprites = set(self.sprites) | {s.id for s in plugin.sprites}
        references = [(s.appearance, f"status {s.id!r}") for s in plugin.statuses] + [
            (m.sprite, f"monster {m.id!r}") for m in plugin.monsters
        ]
        for sprite_id, owner in references:
            if sprite_id is not None and sprite_id not in known_sprites:
                raise PluginLoadError(
                    f"{owner} uses sprite {sprite_id!r}, which is not defined: add define_sprite"
                )
        self.plugins[plugin.id] = plugin
        for _, table, defs in tables:
            for d in defs:
                table[d.id] = d
