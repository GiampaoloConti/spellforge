"""The leaderboard: best run per player, names, persistence, and recording finished runs."""

import json

import pytest
from test_server import Client, new_game, run

from spellforge.engine import Move, Pos
from spellforge.server.leaderboard import (
    FILE_NAME,
    MAX_NAME_LENGTH,
    InvalidName,
    Leaderboard,
    Run,
    clean_name,
)

ALICE = "alice-browser-0001"
BOB = "bob-browser-0002"


def a_run(depth, kills=0, turns=100, when="2026-09-17T10:00:00+00:00", spells=()):
    return Run(depth=depth, kills=kills, turns=turns, spells=list(spells), finished_at=when)


def test_names_are_cleaned_and_checked():
    assert clean_name("  Merlin   the  Grey ") == "Merlin the Grey"
    for bad in ["", "   ", "x" * (MAX_NAME_LENGTH + 1), "evil" + chr(7) + "name"]:
        with pytest.raises(InvalidName):
            clean_name(bad)


def test_each_player_keeps_their_best_run():
    board = Leaderboard()
    assert board.record(ALICE, a_run(3, kills=10))
    assert not board.record(ALICE, a_run(2, kills=50))
    assert board.record(ALICE, a_run(3, kills=12))
    assert board.players[ALICE].runs == 3
    assert board.players[ALICE].best.kills == 12


def test_ranking_is_depth_then_kills_then_fewer_turns():
    board = Leaderboard()
    board.record(ALICE, a_run(4, kills=5, turns=300))
    board.record(BOB, a_run(4, kills=5, turns=200))
    board.record("carol-browser-003", a_run(5, kills=1))
    board.record("dave-browser-0004", a_run(4, kills=9))
    board.rename(BOB, "Bob")
    view = board.view(ALICE)
    assert [(e["rank"], e["depth"], e["kills"]) for e in view["entries"]] == [
        (1, 5, 1),
        (2, 4, 9),
        (3, 4, 5),
        (4, 4, 5),
    ]
    assert view["entries"][2]["name"] == "Bob" and view["entries"][3]["is_you"]
    assert view["you"] is None and view["players"] == 4
    assert all(ALICE not in json.dumps(entry) for entry in view["entries"])  # ids stay private


def test_the_viewer_sees_their_rank_outside_the_top():
    board = Leaderboard()
    for n in range(12):
        board.record(f"player-browser-{n:04}", a_run(20 - n))
    board.record(ALICE, a_run(1))
    view = board.view(ALICE, limit=10)
    assert len(view["entries"]) == 10
    assert view["you"]["rank"] == 13 and view["you"]["is_you"]


def test_the_leaderboard_survives_a_restart(tmp_path):
    board = Leaderboard(tmp_path)
    board.record(ALICE, a_run(6, kills=30, spells=["Sheepify"]))
    board.rename(ALICE, "Alice")
    again = Leaderboard(tmp_path)
    [entry] = again.view(None)["entries"]
    assert entry["name"] == "Alice" and entry["depth"] == 6 and entry["spells"] == ["Sheepify"]


def test_an_unreadable_file_is_kept_aside(tmp_path):
    (tmp_path / FILE_NAME).write_text("{not json", encoding="utf-8")
    board = Leaderboard(tmp_path)
    assert board.players == {}
    assert (tmp_path / "leaderboard.unreadable.json").read_text(encoding="utf-8") == "{not json"


def test_kills_count_enemies_only(make_game):
    game = make_game(["#####", "#@g.#", "#####"])
    game.entities[2].hp = 1
    game.submit(Move(Pos(1, 0)))
    assert game.kills == 1 and game.snapshot()["kills"] == 1


# ---- the session ------------------------------------------------------------------------


async def die(client: Client) -> dict:
    """End the run by killing the player; return the leaderboard message."""
    game = client.session.game
    start = len(game.history)
    game.kill(game.player)
    await client.session._after(game, game.history[start:])
    return client.of_type("leaderboard")[-1]


def test_a_death_is_recorded_and_the_standings_are_sent():
    board = Leaderboard()

    async def scenario():
        client = Client(leaderboard=board)
        await client.send({"type": "identify", "player_id": ALICE, "name": None})
        await client.send(new_game())
        client.session.game.depth = 4
        return await die(client)

    message = run(scenario())
    assert message["recorded"] and message["new_best"]
    assert message["run"]["depth"] == 4 and message["name"] is None
    [entry] = message["entries"]
    assert entry["is_you"] and entry["rank"] == 1 and entry["depth"] == 4


def test_choosing_a_name_updates_the_leaderboard():
    board = Leaderboard()

    async def scenario():
        client = Client(leaderboard=board)
        await client.send({"type": "identify", "player_id": ALICE, "name": None})
        await client.send(new_game())
        await die(client)
        renamed = await client.send({"type": "set_name", "name": "  Alice  "})
        refused = await client.send({"type": "set_name", "name": "x" * 30})
        return renamed, refused

    renamed, refused = run(scenario())
    assert renamed["type"] == "leaderboard" and renamed["name"] == "Alice"
    assert renamed["entries"][0]["name"] == "Alice"
    assert refused["type"] == "error" and "at most 20" in refused["message"]


def test_a_browser_name_is_restored_after_a_server_restart():
    board = Leaderboard()

    async def scenario():
        client = Client(leaderboard=board)
        await client.send({"type": "identify", "player_id": BOB, "name": "Bob"})
        return client

    run(scenario())
    assert board.name_of(BOB) == "Bob"


def test_runs_with_dev_tools_are_not_recorded():
    board = Leaderboard()

    async def scenario():
        client = Client(leaderboard=board, dev_tools=True)
        await client.send(new_game())
        await client.send({"type": "dev", "command": "give_shard"})
        return await die(client)

    message = run(scenario())
    assert not message["recorded"] and board.players == {}


def test_bad_identities_are_rejected():
    reply = run(Client().send({"type": "identify", "player_id": "../../etc", "name": None}))
    assert reply["type"] == "error" and "player_id" in reply["message"]


def test_a_mounted_volume_is_used_without_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("SPELLFORGE_DATA_DIR", raising=False)
    board = Leaderboard.from_env(mounted_volume=tmp_path)
    board.record(ALICE, a_run(2))
    assert (tmp_path / FILE_NAME).exists()
    assert Leaderboard.from_env(mounted_volume=tmp_path / "missing").path is None
    monkeypatch.setenv("SPELLFORGE_DATA_DIR", str(tmp_path / "chosen"))
    assert Leaderboard.from_env(mounted_volume=tmp_path).path == tmp_path / "chosen" / FILE_NAME
