"""Run the game server: `python -m spellforge.server`.

Loads `.env` from the repository root first, so ANTHROPIC_API_KEY enables the forge.
"""

import argparse
import logging

import uvicorn
from dotenv import load_dotenv

from spellforge.server.app import REPO_ROOT

parser = argparse.ArgumentParser(prog="spellforge.server", description="Run the Spellforge server.")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
args = parser.parse_args()

load_dotenv(REPO_ROOT / ".env")
logging.basicConfig(level=logging.INFO)
uvicorn.run("spellforge.server.app:app", host=args.host, port=args.port, reload=args.reload)
