"""Arcane shards: found every third level, carried, and spent at the forge."""

from conftest import events_of

from spellforge.engine import ARCANE_SHARD, Game, Move, Pos, Wait
from spellforge.engine.events import EventType
from spellforge.engine.game import has_shard
from spellforge.plugins import builtin_encounters, default_registry


def test_shards_lie_on_every_third_level():
    assert [d for d in range(1, 11) if has_shard(d)] == [1, 4, 7, 10]


def test_a_new_dungeon_hides_one_shard_outside_the_first_room():
    for seed in range(20):
        game = Game.new(seed, default_registry(), encounters=builtin_encounters)
        [(pos, kind)] = game.items.items()
        assert kind == ARCANE_SHARD
        assert not game.map.is_wall(pos) and game.living_entity_at(pos) is None
        assert pos.distance_to(game.player.pos) > 1
        assert game.snapshot()["items"] == [{"kind": ARCANE_SHARD, "pos": [pos.x, pos.y]}]


def test_shard_placement_is_deterministic():
    first = Game.new(7, default_registry(), encounters=builtin_encounters)
    second = Game.new(7, default_registry(), encounters=builtin_encounters)
    assert first.items == second.items


def test_stepping_on_a_shard_picks_it_up(make_game):
    game = make_game(["#####", "#@*.#", "#####"])
    events = game.submit(Move(Pos(1, 0)))
    assert events_of(events, EventType.ITEM_PICKED_UP) == [
        {"entity": game.player.id, "item": ARCANE_SHARD, "pos": [2, 1], "count": 1}
    ]
    assert game.items == {} and game.inventory == {ARCANE_SHARD: 1}
    assert game.snapshot()["inventory"] == {ARCANE_SHARD: 1}


def test_monsters_do_not_pick_up_shards(make_game):
    game = make_game(["########", "#@...*g#", "########"])
    game.submit(Wait())
    assert game.entities[2].pos == Pos(5, 1)
    assert Pos(5, 1) in game.items and game.inventory == {}


def test_using_a_shard_spends_it(make_game):
    game = make_game(["####", "#@.#", "####"])
    assert not game.use_item(ARCANE_SHARD)
    game.add_item(ARCANE_SHARD, 2)
    assert game.use_item(ARCANE_SHARD)
    assert game.inventory == {ARCANE_SHARD: 1}
    assert events_of(game.history, EventType.ITEM_USED)[-1]["count"] == 1


def test_descending_announces_whether_the_new_level_has_a_shard():
    game = Game.new(3, default_registry(), encounters=builtin_encounters)
    for depth in (2, 3, 4, 5):
        for enemy in [e for e in game.entities.values() if e is not game.player]:
            game.kill(enemy)
        stairs = game.stairs
        beside = next(p for p in stairs.neighbors() if game.is_walkable(p))
        game.player.pos = beside
        events = game.submit(Move(beside.direction_to(stairs)))
        [started] = events_of(events, EventType.LEVEL_STARTED)
        assert started == {"depth": depth, "shard": has_shard(depth)}
        assert bool(game.items) == has_shard(depth)
