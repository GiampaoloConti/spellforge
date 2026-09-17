import asyncio
import json
import random

import pytest
from fastapi.testclient import TestClient
from test_forge import GOOD, ScriptedWriter

from spellforge.agents.forge import SingleAgentForge
from spellforge.agents.spell_writer import Attempt, SpellDraft, SpellRequest
from spellforge.engine import ARCANE_SHARD
from spellforge.server.app import create_app
from spellforge.server.session import FORGE_OFFLINE, NEEDS_SHARD, GameSession


class Client:
    """Drives a GameSession in-process and records everything it sends."""

    def __init__(self, **session_options) -> None:
        self.sent: list[dict] = []

        async def send(message: dict) -> None:
            self.sent.append(message)

        self.session = GameSession(send, **session_options)

    async def send(self, message: dict | str) -> dict:
        count = len(self.sent)
        await self.session.handle(message if isinstance(message, str) else json.dumps(message))
        return self.sent[count] if len(self.sent) > count else {}

    def of_type(self, kind: str) -> list[dict]:
        return [m for m in self.sent if m["type"] == kind]


def run(coro):
    return asyncio.run(coro)


def new_game(seed: int = 42) -> dict:
    return {"type": "new_game", "seed": seed}


WAIT = {"type": "action", "action": {"kind": "wait"}}


# ---- game protocol ----------------------------------------------------------------


def test_new_game_returns_full_state():
    async def scenario():
        client = Client()
        reply = await client.send(new_game())
        assert reply["type"] == "state"
        state = reply["state"]
        assert state["seed"] == 42 and state["turn"] == 1 and state["status"] == "playing"
        assert [s["id"] for s in state["spells"]] == ["firebolt", "frost_nova"]
        player = next(e for e in state["entities"] if e["id"] == state["player_id"])
        assert player["kind"] == "player"
        assert "seed 42" in reply["log"][0]
        assert state["depth"] == 1
        # Plugin sprite art is sent once, then only when new sprites appear.
        assert {"goblin", "orc", "slime"} <= set(reply["sprites"])
        assert len(reply["sprites"]["goblin"]["rows"]) == 16
        assert (await client.send(WAIT))["sprites"] == {}
        json.dumps(reply)

    run(scenario())


def test_same_seed_gives_same_dungeon():
    async def scenario():
        return (await Client().send(new_game(7)), await Client().send(new_game(7)))

    a, b = run(scenario())
    assert a == b


def test_random_seed_when_omitted():
    async def scenario():
        return await Client(rng=random.Random(1)).send({"type": "new_game"})

    assert isinstance(run(scenario())["state"]["seed"], int)


def test_actions_advance_the_game_and_report_events():
    async def scenario():
        client = Client()
        await client.send(new_game())
        return await client.send(WAIT)

    reply = run(scenario())
    assert reply["type"] == "state" and reply["state"]["turn"] == 2
    assert isinstance(reply["events"], list) and isinstance(reply["log"], list)


def test_invalid_action_is_an_error_and_changes_nothing():
    async def scenario():
        client = Client()
        before = (await client.send(new_game()))["state"]
        reply = await client.send({"type": "action", "action": {"kind": "cast", "spell": "meteor"}})
        return client, before, reply

    client, before, reply = run(scenario())
    assert reply == {"type": "error", "message": "you don't know the spell 'meteor'"}
    assert client.session.game.snapshot() == before


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("not json", "malformed message"),
        ('{"type": "dance"}', "malformed message"),
        ('{"type": "action", "action": {"kind": "move", "dx": 2, "dy": 0}}', "action.move.dx"),
        ('{"type": "new_game", "seed": 1, "cheat": true}', "cheat"),
        ('{"type": "invent", "idea": "x"}', "invent.idea"),
        ('{"type": "action", "action": {"kind": "wait"}}', "no game in progress"),
        ('{"type": "new_game", "pad": "' + "x" * 5000 + '"}', "too large"),
    ],
)
def test_bad_messages_are_rejected(raw, fragment):
    reply = run(Client().send(raw))
    assert reply["type"] == "error"
    assert fragment in reply["message"]


# ---- forge --------------------------------------------------------------------------


async def forge(client: Client, idea: str = "a little spark") -> list[dict]:
    """Give the player a shard, ask for a spell and wait until the forge finishes; return the
    forge messages."""
    client.session.game.add_item(ARCANE_SHARD)
    await client.send({"type": "invent", "idea": idea})
    task = client.session._forge_task
    if task is not None:
        await task
    return client.of_type("forge")


def test_forge_offline_without_credentials():
    async def scenario():
        client = Client(forge=None)
        await client.session.start()
        await client.send(new_game())
        return client, await client.send({"type": "invent", "idea": "a fireball"})

    client, reply = run(scenario())
    assert client.sent[0] == {
        "type": "welcome",
        "forge_available": False,
        "forge_status": FORGE_OFFLINE,
        "forge_mode": None,
        "dungeon_master": False,
    }
    assert reply["status"] == "failed" and "ANTHROPIC_API_KEY" in reply["message"]


def test_forged_spell_is_hot_loaded_and_castable():
    async def scenario():
        client = Client(forge=SingleAgentForge(ScriptedWriter(GOOD)))
        await client.send(new_game())
        messages = await forge(client)
        cast = await client.send(
            {"type": "action", "action": {"kind": "cast", "spell": "spark", "target": [0, 0]}}
        )
        await client.session.close()
        return messages, cast

    messages, cast = run(scenario())
    assert messages[0]["status"] == "started" and messages[-1]["status"] == "done"
    assert [m.get("stage") for m in messages[1:4]] == ["writing", "testing", "loading"]
    done = messages[-1]
    assert done["spell"]["name"] == "Spark" and "def on_cast" in done["source"]
    assert "spark" in [s["id"] for s in done["state"]["spells"]]
    assert done["attempts"] == 1 and done["notes"] == "Zap!"
    assert done["sprites"] == {}  # the spark spell defines no art
    # Casting at a wall tile is rejected by the engine, proving the spell is really registered.
    assert cast == {"type": "error", "message": "invalid target tile"}


def test_failed_forge_reports_problems():
    async def scenario():
        client = Client(forge=SingleAgentForge(ScriptedWriter("import os", "import os")))
        await client.send(new_game())
        return await forge(client)

    done = run(scenario())[-1]
    assert done["status"] == "failed"
    assert "kept failing" in done["message"]
    assert any("imports are not allowed" in p for p in done["problems"])


def test_the_forge_needs_a_shard_and_spends_it():
    async def scenario():
        client = Client(forge=SingleAgentForge(ScriptedWriter(GOOD)))
        await client.send(new_game())
        refused = await client.send({"type": "invent", "idea": "a spark"})
        messages = await forge(client)
        await client.session.close()
        return client, refused, messages

    client, refused, messages = run(scenario())
    assert refused == {"type": "forge", "status": "failed", "message": NEEDS_SHARD}
    started = messages[1]
    assert started["status"] == "started" and started["state"]["inventory"] == {ARCANE_SHARD: 0}
    assert messages[-1]["status"] == "done"
    assert client.session.game.inventory == {ARCANE_SHARD: 0}


def test_a_failed_forge_gives_the_shard_back():
    async def scenario():
        client = Client(forge=SingleAgentForge(ScriptedWriter("import os", "import os")))
        await client.send(new_game())
        messages = await forge(client)
        return client, messages[-1]

    client, failed = run(scenario())
    assert failed["status"] == "failed" and failed["message"].endswith("shard is returned.")
    assert failed["state"]["inventory"] == {ARCANE_SHARD: 1}
    assert client.session.game.inventory == {ARCANE_SHARD: 1}


class GatedWriter:
    """A writer that waits until the test releases it, to simulate a slow LLM call."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def write(
        self, request: SpellRequest, previous: list[Attempt], on_progress=None
    ) -> SpellDraft:
        await self.release.wait()
        return SpellDraft(spell_id="spark", notes="", source=GOOD)


def test_game_stays_playable_while_the_forge_works():
    async def scenario():
        writer = GatedWriter()
        client = Client(forge=SingleAgentForge(writer))
        await client.send(new_game())
        client.session.game.add_item(ARCANE_SHARD, 2)
        await client.send({"type": "invent", "idea": "a spark"})
        busy = await client.send({"type": "invent", "idea": "another"})
        played = await client.send(WAIT)
        writer.release.set()
        await client.session._forge_task
        await client.session.close()
        return busy, played, client.of_type("forge")[-1]

    busy, played, done = run(scenario())
    assert busy["status"] == "failed" and "already working" in busy["message"]
    assert played["type"] == "state" and played["state"]["turn"] == 2
    assert done["status"] == "done" and done["state"]["turn"] == 2


def test_new_game_cancels_the_forge():
    async def scenario():
        writer = GatedWriter()
        client = Client(forge=SingleAgentForge(writer))
        await client.send(new_game())
        client.session.game.add_item(ARCANE_SHARD, 2)
        await client.send({"type": "invent", "idea": "a spark"})
        await asyncio.sleep(0)
        reply = await client.send(new_game(43))
        return client, reply

    client, first_reply = run(scenario())
    assert first_reply == {
        "type": "forge",
        "status": "failed",
        "message": "The forge was stopped: a new run began.",
    }
    assert client.session._forge_task is None
    assert "spark" not in client.session.game.registry.spells


# ---- websocket ----------------------------------------------------------------------


def app_client(tmp_path, writer=None, monkeypatch=None) -> TestClient:
    if monkeypatch is not None:
        monkeypatch.setenv("SPELLFORGE_DEV_TOOLS", "1")
    forge = SingleAgentForge(writer) if writer is not None else None
    return TestClient(
        create_app(
            static_dir=tmp_path / "missing",
            forge_factory=lambda: forge,
            dungeon_master_factory=lambda: None,
        )
    )


def test_websocket_round_trip(tmp_path):
    client = app_client(tmp_path)
    assert client.get("/api/health").json() == {
        "status": "ok",
        "forge": False,
        "forge_mode": None,
        "dungeon_master": False,
        "access_code": False,
    }
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "welcome"
        ws.send_text(json.dumps(new_game(3)))
        assert ws.receive_json()["state"]["seed"] == 3
        ws.send_text(json.dumps({"type": "action", "action": {"kind": "move", "dx": 9, "dy": 0}}))
        assert ws.receive_json()["type"] == "error"
        ws.send_text(json.dumps(WAIT))
        assert ws.receive_json()["state"]["turn"] == 2


def test_websocket_forge_pushes_progress_then_the_spell(tmp_path, monkeypatch):
    client = app_client(tmp_path, writer=ScriptedWriter(GOOD), monkeypatch=monkeypatch)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["forge_available"] is True
        ws.send_text(json.dumps(new_game(3)))
        ws.receive_json()
        ws.send_text(json.dumps({"type": "dev", "command": "give_shard"}))
        assert ws.receive_json()["state"]["inventory"] == {ARCANE_SHARD: 1}
        ws.send_text(json.dumps({"type": "invent", "idea": "a little spark"}))
        statuses = []
        while not statuses or statuses[-1] not in ("done", "failed"):
            statuses.append(ws.receive_json()["status"])
        assert statuses[-1] == "done"


def test_each_connection_has_its_own_game(tmp_path):
    client = app_client(tmp_path)
    with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
        first.receive_json(), second.receive_json()
        first.send_text(json.dumps(new_game(1)))
        first.receive_json()
        second.send_text(json.dumps(WAIT))
        assert "no game in progress" in second.receive_json()["message"]


def test_serves_built_frontend_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<h1>spellforge</h1>")
    client = TestClient(
        create_app(
            static_dir=tmp_path,
            forge_factory=lambda: None,
            dungeon_master_factory=lambda: None,
        )
    )
    assert "spellforge" in client.get("/").text
    assert client.get("/api/health").status_code == 200


# ---- dungeon master in the session ----------------------------------------------------


class ScriptedDungeonMaster:
    """Returns a finished counter-monster without calling any model."""

    def __init__(self):
        self.calls = []

    async def create_counter(self, profile, depth, existing, taken_ids, plugin_id, progress):
        from test_dungeon_master import GOLEM, FakeDMAgent, FakeMonsterBalancer
        from test_team import FakeArtist, FakeCoder

        from spellforge.agents.dungeon_master import DungeonMaster

        self.calls.append((profile, depth, plugin_id))
        source = GOLEM.replace("dm_1_art", f"{plugin_id}_art")
        real = DungeonMaster(FakeDMAgent(), FakeMonsterBalancer(), FakeCoder(source), FakeArtist())
        return await real.create_counter(profile, depth, existing, taken_ids, plugin_id, progress)


def test_clearing_a_level_summons_a_counter_monster_for_deeper_levels():
    async def scenario():
        dm = ScriptedDungeonMaster()
        client = Client(dungeon_master=dm)
        await client.session.start()
        await client.send(new_game())
        game = client.session.game
        for enemy in [e for e in game.entities.values() if e is not game.player]:
            if enemy is not list(game.entities.values())[-1]:
                game.kill(enemy)
        last = next(e for e in game.entities.values() if e is not game.player)
        last.hp = 1
        game.player.pos = next(p for p in last.pos.neighbors() if game.is_walkable(p))
        step = game.player.pos.direction_to(last.pos)
        await client.send(
            {"type": "action", "action": {"kind": "move", "dx": step.x, "dy": step.y}}
        )
        await client.session._dm_task
        return client, dm

    client, dm = run(scenario())
    assert client.sent[0]["dungeon_master"] is True
    [(profile, depth, plugin_id)] = dm.calls
    assert depth == 2 and plugin_id.startswith("dm_") and "Reached depth 1" in profile
    messages = [m for m in client.sent if m["type"] == "dungeon_master"]
    assert messages[0]["status"] == "started" and messages[-1]["status"] == "done"
    done = messages[-1]
    assert done["monster"]["name"] == "Warded Golem" and done["monster"]["first_depth"] == 2
    assert done["monster"]["sprite"] in done["sprites"]
    session = client.session
    assert session.counter_monsters == [("warded_golem", 2)]
    assert ("warded_golem", 5) in session.encounters(2)
    assert all(monster != "warded_golem" for monster, _ in session.encounters(1))
    run(session.close())


def test_dev_tools_are_off_unless_enabled():
    async def scenario(dev_tools):
        client = Client(dev_tools=dev_tools)
        await client.send(new_game())
        return client, await client.send({"type": "dev", "command": "clear_level"})

    _, reply = run(scenario(False))
    assert reply == {"type": "error", "message": "dev tools are disabled on this server"}
    client, reply = run(scenario(True))
    assert reply["type"] == "state"
    assert any(event["type"] == "level_cleared" for event in reply["events"])
    assert client.session.game.stairs is not None
    reply = run(client.send({"type": "dev", "command": "descend"}))
    assert reply["state"]["depth"] == 2
