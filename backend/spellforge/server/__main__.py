"""Run the game server: `python -m spellforge.server`."""

import argparse

import uvicorn

parser = argparse.ArgumentParser(prog="spellforge.server", description="Run the Spellforge server.")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
args = parser.parse_args()

uvicorn.run("spellforge.server.app:app", host=args.host, port=args.port, reload=args.reload)
