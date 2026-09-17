import pytest
from conftest import events_of

from spellforge.engine import Cast, EventType, GameStatus, InvalidAction, Move, Pos, Wait

ROOM = [
    "########",
    "#@.....#",
    "#......#",
    "########",
]


def test_player_moves_and_turn_advances(make_game):
    game = make_game(ROOM)
    assert game.turn == 1
    events = game.submit(Move(Pos(1, 0)))
    assert game.player.pos == Pos(2, 1)
    assert game.turn == 2
    assert events_of(events, EventType.MOVED) == [
        {"entity": game.player.id, "how": "step", "from": [1, 1], "to": [2, 1]}
    ]


@pytest.mark.parametrize(
    "action",
    [Move(Pos(0, -1)), Move(Pos(2, 0)), Cast("firebolt", Pos(3, 1)), Cast("nope")],
)
def test_invalid_actions_cost_nothing(make_game, action):
    game = make_game(ROOM)
    before = (game.turn, len(game.history), game.snapshot())
    with pytest.raises(InvalidAction):
        game.submit(action)
    assert (game.turn, len(game.history), game.snapshot()) == before


def test_bump_attack_and_goblin_retaliates(make_game):
    game = make_game(["#####", "#@g.#", "#####"])
    goblin = game.entities[2]
    game.submit(Move(Pos(1, 0)))
    assert game.player.pos == Pos(1, 1)
    assert goblin.hp == 6 - 3
    assert game.player.hp == 20 - 2


def test_goblin_chases_player_it_can_see(make_game):
    game = make_game(ROOM[:1] + ["#@....g#"] + ROOM[2:])
    goblin = game.entities[2]
    game.submit(Wait())
    assert goblin.pos == Pos(5, 1)
    game.submit(Wait())
    game.submit(Wait())
    game.submit(Wait())
    assert goblin.pos == Pos(2, 1)
    assert game.player.hp == 20
    game.submit(Wait())
    assert goblin.pos == Pos(2, 1)
    assert game.player.hp == 20 - 2


def test_goblin_does_not_see_through_walls(make_game):
    game = make_game(["#########", "#@..#..g#", "#########"], seed=3)
    goblin = game.entities[2]
    for _ in range(5):
        game.submit(Wait())
    assert goblin.pos.x >= 5  # wandered at most within its side of the wall


def test_clearing_a_level_opens_stairs_on_the_farthest_tile(make_game):
    game = make_game(["#######", "#@g...#", "#.....#", "#######"])
    game.entities[2].hp = 1
    events = game.submit(Move(Pos(1, 0)))
    # (5, 1) and (5, 2) are equally far in king moves; ties go to the topmost tile.
    assert events_of(events, EventType.LEVEL_CLEARED) == [{"depth": 1, "stairs": [5, 1]}]
    assert game.stairs == Pos(5, 1) and game.map.to_ascii()[1] == "#....>#"
    assert game.status is GameStatus.PLAYING


def test_stepping_on_stairs_descends_to_a_harder_level(make_game):
    game = make_game(["#####", "#@g>#", "#####"])
    game.entities[2].hp = 1
    game.submit(Move(Pos(1, 0)))  # kill the goblin; stairs open on its side
    game.player.hp, game.player.mana = 10, 2
    game.submit(Move(Pos(1, 0)))
    turn_before = game.turn
    events = game.submit(Move(Pos(1, 0)))
    assert events_of(events, EventType.LEVEL_STARTED) == [{"depth": 2, "shard": False}]
    assert game.depth == 2 and game.turn == turn_before + 1
    assert game.stairs is None and ">" not in "".join(game.map.to_ascii())
    assert game.player.hp == 10 + 5 and game.player.mana == game.player.max_mana
    monsters = [e for e in game.entities.values() if e is not game.player]
    assert monsters and all(m.kind == "goblin" for m in monsters)
    assert not game.map.is_wall(game.player.pos)
    assert not any(e.type is EventType.ATTACKED for e in events)  # monsters wait a round


def test_the_stairs_tile_is_not_walkable_before_it_opens(make_game):
    game = make_game(["#####", "#@..#", "#####"])
    game.submit(Move(Pos(1, 0)))
    assert game.depth == 1


def test_deeper_levels_have_more_and_varied_monsters():
    from spellforge.engine import Game
    from spellforge.engine.game import monsters_per_room
    from spellforge.plugins import default_registry

    assert monsters_per_room(1) == (1, 2)
    assert monsters_per_room(9) == (3, 5)
    table = lambda depth: [("goblin", 3), ("not_a_monster", 5)]  # noqa: E731
    game = Game.new(5, default_registry(), encounters=table)
    assert {e.kind for e in game.entities.values()} == {"player", "goblin"}


def test_player_death_ends_the_run(make_game):
    game = make_game(["#####", "#@g.#", "#####"])
    game.player.hp = 2
    events = game.submit(Wait())
    assert game.status is GameStatus.LOST
    assert not game.player.alive
    assert events_of(events, EventType.GAME_OVER) == [{"result": "lost", "depth": 1}]
    with pytest.raises(InvalidAction, match="over"):
        game.submit(Wait())


def test_allies_fight_enemies(make_game):
    game = make_game(["########", "#@..Gg.#", "########"])
    ally, enemy = game.entities[2], game.entities[3]
    assert (ally.faction, enemy.faction) == ("player", "enemy")
    game.submit(Wait())
    assert enemy.hp == 6 - 2
    assert ally.hp == 6 - 2
    assert game.player.hp == 20


def test_player_cannot_walk_into_an_ally(make_game):
    game = make_game(["#####", "#@G.#", "#####"])
    with pytest.raises(InvalidAction, match="in the way"):
        game.submit(Move(Pos(1, 0)))


def test_mana_regenerates_up_to_max(make_game):
    game = make_game(ROOM, spells=("firebolt",))
    game.submit(Cast("firebolt", Pos(6, 1)))
    assert game.player.mana == 10 - 3 + 1
    for _ in range(5):
        game.submit(Wait())
    assert game.player.mana == 10


def test_snapshot_is_json_ready(make_game):
    import json

    game = make_game(["#####", "#@g.#", "#####"], spells=("firebolt",))
    game.submit(Wait())
    data = json.loads(json.dumps(game.snapshot()))
    assert data["turn"] == 2
    assert data["spells"][0]["id"] == "firebolt"
    assert {e["kind"] for e in data["entities"]} == {"player", "goblin"}
    json.dumps([e.to_dict() for e in game.history])


def test_monsters_queue_up_behind_each_other_in_corridors(make_game):
    game = make_game(["#########", "#@...gg.#", "#########"])
    front, back = game.entities[2], game.entities[3]
    game.submit(Wait())
    assert (front.pos, back.pos) == (Pos(4, 1), Pos(5, 1))
