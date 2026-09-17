"""Deployment guards: invite code, daily spending cap, concurrent sessions, OS hardening."""

import asyncio
import json
import subprocess
import sys
from datetime import date

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_forge import GOOD, ScriptedWriter
from test_server import Client, forge, new_game, run

from spellforge.agents.forge import SingleAgentForge
from spellforge.server.app import SERVER_FULL, create_app
from spellforge.server.limits import (
    MAX_UNLOCK_ATTEMPTS,
    AccessGate,
    SessionSlots,
    SpendingCap,
)
from spellforge.server.session import BUDGET_SPENT


def test_gate_is_open_without_a_code():
    assert not AccessGate(None).required and AccessGate("").check("anything")
    gate = AccessGate(" friends-only-7f3a ")
    assert gate.required
    assert gate.check("friends-only-7f3a") and gate.check(" friends-only-7f3a\n")
    assert not gate.check("friends-only") and not gate.check("")


def test_spending_cap_reserves_then_settles_and_resets_daily():
    day = [date(2026, 9, 17)]
    cap = SpendingCap(0.30, today=lambda: day[0])
    first = cap.reserve(0.15)
    second = cap.reserve(0.15)
    assert first and second and cap.reserve(0.15) is None
    cap.settle(first, 0.05)
    assert cap.spent_today == pytest.approx(0.20) and cap.available()
    cap.settle(second, None)  # unknown cost (cancelled): the estimate stays
    assert cap.spent_today == pytest.approx(0.20)
    day[0] = date(2026, 9, 18)
    assert cap.spent_today == 0 and cap.available()
    cap.settle(first, 9.99)  # yesterday's run does not count against today
    assert cap.spent_today == 0


def test_no_cap_means_unlimited():
    cap = SpendingCap(None)
    assert all(cap.reserve(100.0) for _ in range(10))


def test_session_slots():
    slots = SessionSlots(2)
    assert slots.acquire() and slots.acquire() and not slots.acquire()
    slots.release()
    assert slots.acquire()
    assert all(SessionSlots(None).acquire() for _ in range(100))


def test_forge_refuses_when_the_daily_budget_is_spent():
    async def scenario():
        cap = SpendingCap(0.10)
        client = Client(forge=SingleAgentForge(ScriptedWriter(GOOD)), spending=cap)
        await client.send(new_game())
        cap.reserve(0.10)
        return client, (await forge(client))[-1]

    client, reply = run(scenario())
    assert reply == {"type": "forge", "status": "failed", "message": BUDGET_SPENT}
    assert client.session._forge_task is None


def test_forge_records_its_real_cost():
    async def scenario():
        cap = SpendingCap(5.0)
        client = Client(forge=SingleAgentForge(ScriptedWriter(GOOD)), spending=cap)
        await client.send(new_game())
        messages = await forge(client)
        await client.session.close()
        return cap, messages[-1]

    cap, done = run(scenario())
    assert done["status"] == "done"
    assert cap.spent_today == pytest.approx(done["cost_usd"], abs=1e-4)  # scripted: $0


def gated_app(tmp_path, **options) -> TestClient:
    return TestClient(
        create_app(
            static_dir=tmp_path / "missing",
            forge_factory=lambda: None,
            dungeon_master_factory=lambda: None,
            gate=AccessGate("open-sesame"),
            wrong_code_delay=0,
            **options,
        )
    )


def test_websocket_needs_the_invite_code_first(tmp_path):
    client = gated_app(tmp_path)
    assert client.get("/api/health").json()["access_code"] is True
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "locked", "error": None}
        ws.send_text(json.dumps(new_game(3)))
        assert ws.receive_json()["error"] == "Enter the invite code first."
        ws.send_text(json.dumps({"type": "unlock", "code": "guess"}))
        assert ws.receive_json()["error"] == "That invite code is not right."
        ws.send_text(json.dumps({"type": "unlock", "code": "open-sesame"}))
        assert ws.receive_json()["type"] == "welcome"
        ws.send_text(json.dumps(new_game(3)))
        assert ws.receive_json()["state"]["seed"] == 3


def test_too_many_wrong_codes_close_the_connection(tmp_path):
    client = gated_app(tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        for _ in range(MAX_UNLOCK_ATTEMPTS):
            ws.send_text(json.dumps({"type": "unlock", "code": "nope"}))
            last = ws.receive_json()
        assert last["error"].startswith("Too many wrong codes")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_a_full_server_turns_new_players_away(tmp_path):
    slots = SessionSlots(1)
    client = gated_app(tmp_path, slots=slots)
    with client.websocket_connect("/ws") as first:
        first.receive_json()
        with client.websocket_connect("/ws") as second:
            assert second.receive_json() == {"type": "error", "message": SERVER_FULL}
    assert slots.active == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process restrictions")
def test_worker_restrictions_block_processes_writes_and_network(tmp_path):
    probe = f"""
import socket, subprocess, sys
from spellforge.sandbox.hardening import restrict_worker
applied = restrict_worker(512 * 1024 * 1024)
results = {{"applied": applied}}
try:
    subprocess.run(["true"])
    results["spawn"] = "allowed"
except OSError:
    results["spawn"] = "blocked"
try:
    with open({str(tmp_path / "x.txt")!r}, "w") as f:
        f.write("data")
        f.flush()
    results["write"] = "allowed"
except OSError:
    results["write"] = "blocked"
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
    results["network"] = "allowed"
except OSError:
    results["network"] = "blocked"
print(results)
"""
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    results = eval(out.stdout)  # our own probe's dict literal
    assert {"memory cap", "no file writes", "no new processes"} <= set(results["applied"])
    assert results["spawn"] == "blocked" and results["write"] == "blocked"
    if "no network" in results["applied"]:
        assert results["network"] == "blocked"


def test_session_accepts_a_spending_cap():
    session_cap = SpendingCap(1.0)
    client = Client(spending=session_cap)
    assert client.session._spending is session_cap
    asyncio.run(client.session.close())
