"""FastAPI app: a websocket per player, plus the built frontend when it exists.

Each websocket connection owns one `GameSession`. The game is authoritative on the
server; the browser only sends inputs and draws the state it receives.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from spellforge.server.session import GameSession

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATIC_DIR = REPO_ROOT / "frontend" / "dist"


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Spellforge")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def play(websocket: WebSocket) -> None:
        await websocket.accept()
        session = GameSession()
        try:
            while True:
                raw = await websocket.receive_text()
                await websocket.send_json(session.handle(raw))
        except WebSocketDisconnect:
            return

    # Serve the production build of the frontend, if it has been built.
    # Mounted last so it does not shadow the routes above.
    static_dir = static_dir or Path(os.environ.get("SPELLFORGE_STATIC_DIR", DEFAULT_STATIC_DIR))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
