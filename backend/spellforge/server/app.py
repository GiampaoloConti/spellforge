"""FastAPI app: a websocket per player, plus the built frontend when it exists.

Each websocket connection owns one `GameSession`. The game is authoritative on the
server; the browser only sends inputs and draws the state it receives. The forge pushes
progress messages on the same socket while the player keeps playing.
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

from spellforge.agents.dungeon_master import DungeonMaster
from spellforge.agents.factory import make_dungeon_master, make_spell_forge
from spellforge.agents.forge import SpellForge
from spellforge.agents.llm import credentials_available
from spellforge.server.session import GameSession

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATIC_DIR = REPO_ROOT / "frontend" / "dist"

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
) -> FastAPI:
    app = FastAPI(title="Spellforge")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        forge = forge_factory()
        return {
            "status": "ok",
            "forge": forge is not None,
            "forge_mode": forge.mode if forge is not None else None,
            "dungeon_master": dungeon_master_factory() is not None,
        }

    @app.websocket("/ws")
    async def play(websocket: WebSocket) -> None:
        await websocket.accept()
        send_lock = asyncio.Lock()
        connected = True

        async def send(message: dict[str, Any]) -> None:
            # The forge pushes from a background task; serialize writes to the socket.
            async with send_lock:
                if connected:
                    await websocket.send_json(message)

        session = GameSession(
            send,
            forge=forge_factory(),
            dungeon_master=dungeon_master_factory(),
            dev_tools=os.environ.get("SPELLFORGE_DEV_TOOLS") == "1",
        )
        try:
            await session.start()
            while True:
                await session.handle(await websocket.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            connected = False
            await session.close()

    # Serve the production build of the frontend, if it has been built.
    # Mounted last so it does not shadow the routes above.
    static_dir = static_dir or Path(os.environ.get("SPELLFORGE_STATIC_DIR", DEFAULT_STATIC_DIR))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
