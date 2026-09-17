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


def test_killing_the_last_enemy_wins(make_game):
    game = make_game(["#####", "#@g.#", "#####"])
    game.entities[2].hp = 1
    events = game.submit(Move(Pos(1, 0)))
    assert game.status is GameStatus.WON
    assert events_of(events, EventType.GAME_OVER) == [{"result": "won"}]
    assert 2 not in game.entities
    with pytest.raises(InvalidAction, match="over"):
        game.submit(Wait())


def test_player_death_loses(make_game):
    game = make_game(["#####", "#@g.#", "#####"])
    game.player.hp = 2
    game.submit(Wait())
    assert game.status is GameStatus.LOST
    assert not game.player.alive


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
