"""FastAPI app: a websocket per player, plus the built frontend when it exists.

Each websocket connection owns one `GameSession`. The game is authoritative on the
server; the browser only sends inputs and draws the state it receives. The forge pushes
progress messages on the same socket while the player keeps playing.

For a public deployment (see `docs/deploy.md`) the environment can require an invite code,
cap daily AI spending and cap concurrent players; all three are off by default. The
leaderboard is shared by all connections and saved under SPELLFORGE_DATA_DIR.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import anthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from spellforge.agents.dungeon_master import DungeonMaster
from spellforge.agents.factory import make_dungeon_master, make_spell_forge
from spellforge.agents.forge import SpellForge
from spellforge.agents.llm import credentials_available
from spellforge.server.leaderboard import Leaderboard
from spellforge.server.limits import MAX_UNLOCK_ATTEMPTS, AccessGate, SessionSlots, SpendingCap
from spellforge.server.protocol import (
    MAX_MESSAGE_BYTES,
    error_message,
    locked_message,
    unlock_message,
)
from spellforge.server.session import GameSession

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATIC_DIR = REPO_ROOT / "frontend" / "dist"
WRONG_CODE_DELAY = 1.0
SERVER_FULL = "The dungeon is full right now. Try again in a few minutes."

ForgeFactory = Callable[[], SpellForge | None]
DungeonMasterFactory = Callable[[], DungeonMaster | None]


@cache
def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic()


@cache
def default_forge() -> SpellForge | None:
    """The configured forge (agent team by default), if credentials are configured."""
    return make_spell_forge(client=_client()) if credentials_available() else None


@cache
def default_dungeon_master() -> DungeonMaster | None:
    return make_dungeon_master(client=_client()) if credentials_available() else None


def create_app(
    static_dir: Path | None = None,
    forge_factory: ForgeFactory = default_forge,
    dungeon_master_factory: DungeonMasterFactory = default_dungeon_master,
    gate: AccessGate | None = None,
    spending: SpendingCap | None = None,
    slots: SessionSlots | None = None,
    leaderboard: Leaderboard | None = None,
    wrong_code_delay: float = WRONG_CODE_DELAY,
) -> FastAPI:
    app = FastAPI(title="Spellforge")
    gate = gate or AccessGate.from_env()
    spending = spending or SpendingCap.from_env()
    slots = slots or SessionSlots.from_env()
    leaderboard = leaderboard or Leaderboard.from_env()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        forge = forge_factory()
        return {
            "status": "ok",
            "forge": forge is not None,
            "forge_mode": forge.mode if forge is not None else None,
            "dungeon_master": dungeon_master_factory() is not None,
            "access_code": gate.required,
        }

    async def unlock(websocket: WebSocket) -> bool:
        """Ask for the invite code until it is right, or give up after a few attempts."""
        await websocket.send_json(locked_message())
        for attempt in range(1, MAX_UNLOCK_ATTEMPTS + 1):
            raw = await websocket.receive_text()
            try:
                code = unlock_message.validate_json(raw[:MAX_MESSAGE_BYTES]).code
            except ValidationError:
                await websocket.send_json(locked_message("Enter the invite code first."))
                continue
            if gate.check(code):
                return True
            await asyncio.sleep(wrong_code_delay)  # makes guessing slow
            if attempt < MAX_UNLOCK_ATTEMPTS:
                await websocket.send_json(locked_message("That invite code is not right."))
        await websocket.send_json(locked_message("Too many wrong codes. Reload to try again."))
        await websocket.close(code=1008)
        return False

    @app.websocket("/ws")
    async def play(websocket: WebSocket) -> None:
        await websocket.accept()
        if not slots.acquire():
            await websocket.send_json(error_message(SERVER_FULL))
            await websocket.close(code=1013)
            return
        send_lock = asyncio.Lock()
        connected = True

        async def send(message: dict[str, Any]) -> None:
            # The forge pushes from a background task; serialize writes to the socket.
            async with send_lock:
                if connected:
                    await websocket.send_json(message)

        session: GameSession | None = None
        try:
            if gate.required and not await unlock(websocket):
                return
            session = GameSession(
                send,
                forge=forge_factory(),
                dungeon_master=dungeon_master_factory(),
                dev_tools=os.environ.get("SPELLFORGE_DEV_TOOLS") == "1",
                spending=spending,
                leaderboard=leaderboard,
            )
            await session.start()
            while True:
                await session.handle(await websocket.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            connected = False
            slots.release()
            if session is not None:
                await session.close()

    # Serve the production build of the frontend, if it has been built.
    # Mounted last so it does not shadow the routes above.
    static_dir = static_dir or Path(os.environ.get("SPELLFORGE_STATIC_DIR", DEFAULT_STATIC_DIR))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
