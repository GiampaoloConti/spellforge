# Spellforge

**A roguelike where you invent the spells, and a team of AI agents writes them into the game while you play.**

> "A spell that turns enemies into sheep, but they explode after 3 turns."

You type it. A multi-agent pipeline designs it, balances it, writes it as code, tests it in a sandbox and hot-loads it into the running game. A few seconds later, you cast it.

🚧 **Work in progress.** See the roadmap below.

## How it works

```
                          ┌─► Balancer ── nerfs broken ideas ─┐
 your idea ─► Designer ───┼─► Coder (starts early) ───────────┼─► Tester ─► hot-loaded into the game
               spec       └─► Artist (pixel art) ─────────────┘  sandbox sim, ↺ retries

 clear a level ─► Dungeon Master studies how you fight ─► a new monster built to counter you
```

- **Deterministic engine, generated content.** A small hand-written Python engine runs the game. Everything creative is a plugin written by agents against a narrow plugin API.
- **Agents never block the game.** They work between turns, and the game stays playable.
- **Generated code is sandboxed.** It goes through static AST checks, then runs in an isolated process with resource limits and access to the plugin API only.
- **Nothing crashes the game.** Plugins that fail are disabled and replaced with safe fallbacks.
- **Balance is measured, not just judged.** Every forged spell is cast among training dummies; damage, healing, crowd control, summons and reach are checked against limits set by its mana cost, and anything over budget goes back to the Balancer with the numbers.
- **The dungeon fights back.** When you clear a level, a Dungeon Master agent reads how you play and designs a monster to counter it, which goes through the same balance, code and test pipeline.
- **Measured, not claimed.** Benchmarks compare model choices and the single agent against the team on success rate, cost and latency ([docs/agents.md](docs/agents.md)).

## Try it

Requires Python 3.11+ and Node 20.19+ (or 22.12+).

```bash
# 1. Backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows (Git Bash); use bin/activate elsewhere
pip install -e ".[dev]"

# 2. Frontend (one-off build, served by the Python server)
cd ../frontend
npm install && npm run build

# 3. Enable the forge: put your Anthropic API key in .env at the repo root
#    ANTHROPIC_API_KEY=sk-ant-...

# 4. Play at http://127.0.0.1:8000
cd ../backend
python -m spellforge.server
```

Find the arcane shard hidden on the first level (another waits every third level), then press
<kbd>F</kbd>, describe a spell, press <kbd>Enter</kbd>, and keep playing while the agents write
it (usually 15-25 seconds). The dungeon is endless: clear a level, take the stairs, and see how
deep you get. Without an API key the game still works; the forge just stays offline.

To host it for friends on Hugging Face Spaces, with your key kept as a secret, an invite code
and a daily spending cap, see [docs/deploy.md](docs/deploy.md).

For frontend development, run `python -m spellforge.server` and `npm run dev` side by side,
then open http://localhost:5173. There is also a terminal version: `python -m spellforge`.

Tests: `pytest` in `backend/`, `npm test` in `frontend/`.

Design notes: [the agent team and the Dungeon Master](docs/agents.md),
[the forge: sandbox and verification](docs/forge.md),
[forge model benchmark](docs/evals/forge-models.md),
[plugin API](docs/plugin-api.md) (what agents write against) and
[client/server protocol](docs/protocol.md).

## Stack

Python (engine, agents, sandbox, FastAPI websocket server) · TypeScript (canvas renderer) · Claude (Anthropic API)

## Roadmap

- [x] M1: Deterministic grid engine plus plugin API
- [x] M2: Browser client
- [x] M3: Single agent writes plugins at runtime
- [x] M4: Agent team (designer, balancer, coder, artist, tester) plus a Dungeon Master that counters your play style
- [x] M5: Playable by friends: Hugging Face deployment with an invite code and spending cap, measured balance, arcane shards gate the forge, UI redesign
- [ ] M6: Evals (single agent vs. team) and demo
