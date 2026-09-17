import pytest
from conftest import events_of, plugin

from spellforge.engine import (
    Cast,
    EventType,
    Game,
    PluginLoadError,
    Registry,
    Wait,
    load_plugin,
)
from spellforge.plugins import builtin_encounters, default_registry
from spellforge.sandbox.host import PluginSandbox

LEGEND = {
    "g": "goblin",
    "b": "bat",
    "a": "skeleton_archer",
    "s": "slime",
    "o": "orc",
    "h": "goblin_shaman",
}


def arena(rows, seed=0, spells=(), plugins=()):
    registry = default_registry()
    for extra in plugins:
        registry.add(extra)
    return Game.from_ascii(rows, registry, LEGEND, seed=seed, spells=spells)


# ---- monsters -----------------------------------------------------------------------


def test_skeleton_archer_shoots_from_range_and_backs_off_up_close():
    game = arena(["##########", "#@....a..#", "##########"])
    archer = game.entities[2]
    events = game.submit(Wait())
    assert game.player.hp == 20 - 2
    assert any("looses an arrow" in e["text"] for e in events_of(events, EventType.MESSAGE))

    close = arena(["#######", "#.....#", "#@a...#", "#.....#", "#######"])
    archer = close.entities[2]
    close.submit(Wait())
    assert archer.pos.distance_to(close.player.pos) == 2
    assert close.player.hp == 20


def test_slime_is_slow_and_splits_when_killed():
    game = arena(["#########", "#@.....s#", "#.......#", "#########"])
    slime = game.entities[2]
    start = slime.pos
    game.submit(Wait())  # turn 1: odd, the slime only prepares
    assert slime.pos == start and "splitting" in slime.statuses
    game.submit(Wait())  # turn 2: it moves
    assert slime.pos != start
    game.damage(slime, 99, source=game.player.id)
    kinds = [e.kind for e in game.entities.values()]
    assert kinds.count("slimeling") == 2 and "slime" not in kinds


def test_goblin_shaman_heals_wounded_allies():
    game = arena(["###########", "#@......hg#", "###########"])
    goblin = game.entities[3]
    goblin.hp = 2
    events = game.submit(Wait())
    assert goblin.hp == 5
    assert any("heals the goblin" in e["text"] for e in events_of(events, EventType.MESSAGE))


def test_orc_is_tough_and_hits_hard():
    game = arena(["#####", "#@o.#", "#####"])
    game.submit(Wait())
    assert game.player.hp == 20 - 4
    assert game.entities[2].max_hp == 16


def test_encounter_table_unlocks_monsters_with_depth():
    def kinds(depth):
        return {monster for monster, _ in builtin_encounters(depth)}

    assert kinds(1) == {"goblin", "bat"}
    assert {"skeleton_archer", "slime"} <= kinds(2) and "orc" not in kinds(2)
    assert {"orc", "goblin_shaman"} <= kinds(3)
    assert dict(builtin_encounters(8))["orc"] > dict(builtin_encounters(3))["orc"]


def test_every_builtin_monster_has_a_sprite():
    registry = default_registry()
    for monster in registry.monsters.values():
        assert monster.sprite in registry.sprites, monster.id


# ---- sprites --------------------------------------------------------------------------

ROCK = {
    "palette": {"k": "#140d1c", "r": "#8a8f99", "R": "#b7bcc6"},
    "rows": ["." * 16] * 6
    + ["....kkkkkkkk...."]
    + ["...kRRrrrrrrk..."] * 6
    + ["..krrrrrrrrrrk.."]
    + ["..kkkkkkkkkkkk.."]
    + ["." * 16],
}

PETRIFY = f"""
def on_cast(ctx, caster, target):
    victim = ctx.entity_at(target)
    if victim is not None:
        ctx.apply_status(victim.id, "petrified", 3, source=caster)

define_sprite(id="rock", palette={ROCK["palette"]!r}, rows={ROCK["rows"]!r})
define_status(id="petrified", name="Petrified", description="Turned to stone.",
              prevents_action=True, appearance="rock")
define_spell(id="petrify", name="Petrify", description="Turns a creature to stone.",
             mana_cost=4, target="entity", range=5, on_cast=on_cast)
"""


def test_status_appearance_changes_how_a_creature_is_drawn():
    game = arena(
        ["######", "#@.g.#", "######"], spells=("petrify",), plugins=(plugin("petrify", PETRIFY),)
    )
    goblin = game.entities[2]
    assert game.appearance(goblin) == "goblin"
    game.submit(Cast("petrify", goblin.pos))
    [entry] = [e for e in game.snapshot()["entities"] if e["id"] == goblin.id]
    assert entry["appearance"] == "rock"
    assert game.sprite_art({"rock"})["rock"]["rows"] == ROCK["rows"]
    for _ in range(3):
        game.submit(Wait())
    assert game.appearance(goblin) == "goblin"  # back to normal when the status expires


def test_player_uses_client_art_by_default():
    game = arena(["####", "#@.#", "####"])
    assert game.snapshot()["entities"][0]["appearance"] is None


def test_sprites_pass_through_the_sandbox():
    sandbox, loaded = PluginSandbox.start("petrify", PETRIFY)
    try:
        assert [s.id for s in loaded.sprites] == ["rock"]
        assert loaded.statuses[0].appearance == "rock"
        assert loaded.sprites[0].rows == tuple(ROCK["rows"])
    finally:
        sandbox.close()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("'#8a8f99'", "'grey'", "must look like '#1a2b3c'"),
        ("'....kkkkkkkk....'", "'....kkkkkkkk...'", "row 6 must be a string of 16"),
        ("'...kRRrrrrrrk...'", "'...kRRzzzzzzk...'", "missing from the palette"),
        ('appearance="rock"', 'appearance="boulder"', "not defined: add define_sprite"),
        ("'k': '#140d1c'", "'.': '#140d1c'", "must be one printable character, not '.'"),
    ],
)
def test_bad_sprites_are_rejected(old, new, message):
    assert old in PETRIFY
    with pytest.raises(PluginLoadError, match=message):
        Registry([load_plugin("petrify", PETRIFY.replace(old, new, 1))])


def test_sprite_ids_cannot_clash():
    registry = default_registry()
    clash = PETRIFY.replace('define_sprite(id="rock"', 'define_sprite(id="goblin"').replace(
        'appearance="rock"', 'appearance="goblin"'
    )
    with pytest.raises(PluginLoadError, match="sprite id"):
        registry.add(load_plugin("petrify", clash))
