import json
import random

import pytest
from fastapi.testclient import TestClient

from spellforge.server.app import create_app
from spellforge.server.session import GameSession


def send(session: GameSession, message: dict) -> dict:
    return session.handle(json.dumps(message))


def test_new_game_returns_full_state():
    reply = send(GameSession(), {"type": "new_game", "seed": 42})
    assert reply["type"] == "state"
    state = reply["state"]
    assert state["seed"] == 42 and state["turn"] == 1 and state["status"] == "playing"
    assert [s["id"] for s in state["spells"]] == ["firebolt", "frost_nova"]
    player = next(e for e in state["entities"] if e["id"] == state["player_id"])
    assert player["kind"] == "player"
    assert "seed 42" in reply["log"][0]
    json.dumps(reply)


def test_same_seed_gives_same_dungeon():
    a = send(GameSession(), {"type": "new_game", "seed": 7})
    b = send(GameSession(), {"type": "new_game", "seed": 7})
    assert a == b


def test_random_seed_when_omitted():
    reply = send(GameSession(rng=random.Random(1)), {"type": "new_game"})
    assert isinstance(reply["state"]["seed"], int)


def test_actions_advance_the_game_and_report_events():
    session = GameSession()
    send(session, {"type": "new_game", "seed": 42})
    reply = send(session, {"type": "action", "action": {"kind": "wait"}})
    assert reply["type"] == "state" and reply["state"]["turn"] == 2
    assert isinstance(reply["events"], list) and isinstance(reply["log"], list)


def test_invalid_action_is_an_error_and_changes_nothing():
    session = GameSession()
    before = send(session, {"type": "new_game", "seed": 42})["state"]
    reply = send(session, {"type": "action", "action": {"kind": "cast", "spell": "meteor"}})
    assert reply == {"type": "error", "message": "you don't know the spell 'meteor'"}
    assert session.game is not None and session.game.snapshot() == before


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("not json", "malformed message"),
        ('{"type": "dance"}', "malformed message"),
        ('{"type": "action", "action": {"kind": "move", "dx": 2, "dy": 0}}', "action.move.dx"),
        ('{"type": "new_game", "seed": 1, "cheat": true}', "cheat"),
        ('{"type": "action", "action": {"kind": "wait"}}', "no game in progress"),
        ('{"type": "new_game", "pad": "' + "x" * 5000 + '"}', "too large"),
    ],
)
def test_bad_messages_are_rejected(raw, fragment):
    reply = GameSession().handle(raw)
    assert reply["type"] == "error"
    assert fragment in reply["message"]


def test_websocket_round_trip(tmp_path):
    client = TestClient(create_app(static_dir=tmp_path / "missing"))
    assert client.get("/api/health").json() == {"status": "ok"}
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "new_game", "seed": 3}))
        assert ws.receive_json()["state"]["seed"] == 3
        ws.send_text(json.dumps({"type": "action", "action": {"kind": "move", "dx": 9, "dy": 0}}))
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps({"type": "action", "action": {"kind": "wait"}}))
        assert ws.receive_json()["state"]["turn"] == 2


def test_each_connection_has_its_own_game(tmp_path):
    client = TestClient(create_app(static_dir=tmp_path / "missing"))
    with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
        first.send_text(json.dumps({"type": "new_game", "seed": 1}))
        first.receive_json()
        second.send_text(json.dumps({"type": "action", "action": {"kind": "wait"}}))
        assert "no game in progress" in second.receive_json()["message"]


def test_serves_built_frontend_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<h1>spellforge</h1>")
    client = TestClient(create_app(static_dir=tmp_path))
    assert "spellforge" in client.get("/").text
    assert client.get("/api/health").status_code == 200
