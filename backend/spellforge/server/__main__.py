"""Run the game server: `python -m spellforge.server`.

Loads `.env` from the repository root first, so ANTHROPIC_API_KEY enables the forge. HOST and
PORT environment variables set the defaults for --host and --port (used by the Docker image).
"""

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from spellforge.sandbox.hardening import protect_server_process

# Before importing the app: it reads its configuration from the environment.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

parser = argparse.ArgumentParser(prog="spellforge.server", description="Run the Spellforge server.")
parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
args = parser.parse_args()

logging.basicConfig(level=logging.INFO)
protect_server_process()
uvicorn.run("spellforge.server.app:app", host=args.host, port=args.port, reload=args.reload)
