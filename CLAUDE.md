# CLAUDE.md

Guidance for Claude Code working in this repository. **Read this first, then check "Current status" to see where to pick up.**

## Project

**Spellforge** is a turn-based, grid roguelike where the game's content is created at runtime by a team of AI agents. The player types an ability they want ("a spell that turns enemies into sheep that explode after 3 turns"), and a multi-agent pipeline designs, balances, writes, tests and hot-loads it as code into the running game.

Goal: a portfolio / GitHub showcase project for the owner, an AI engineer targeting SF startups. It should demonstrate **real multi-agent engineering**: role separation with isolated context, adversarial review, verification loops, sandboxed code execution and measured results (a single agent vs. the team). Polish, a clear README and a demo GIF matter as much as the features.

## Owner context

- Strong in **Python**; **new to TypeScript**. Keep the frontend small and idiomatic, and explain TS concepts briefly when writing frontend code.
- LLM provider: **Claude (Anthropic API)**. Before writing LLM code, check the current Claude model IDs and SDK usage instead of relying on memory.
- Windows 11 dev machine.

## Architecture (decided)

```
Browser (TypeScript)             Python backend
┌──────────────┐  websocket   ┌──────────────────────────────────┐
│ grid renderer│◄────────────►│ Game engine (deterministic)      │
│ input        │              │  turn loop · entities · events   │
│ "invent" box │              │  plugin API (the only surface)   │
└──────────────┘              │            ▲ hot-load            │
                              │ Agent team (async)               │
                              │  designer → balancer → coder     │
                              │        → tester (sandbox sim)    │
                              │            ↺ retry on failure    │
                              └──────────────────────────────────┘
```

Key decisions and why:

1. **Turn-based, so the server holds authority.** All game state and rules live in Python. The browser is a thin renderer that sends inputs and draws state received over a websocket. This keeps the owner in Python.
2. **Agents never run inside the game loop.** They act *between moments* (the player invents an ability, a room loads, a floor ends). LLM latency is hidden behind gameplay ("the arcane forge is working…"). The game must stay playable while agents work.
3. **Small, fixed engine plus generated plugins.** The engine is hand-written, deterministic (seeded RNG) and stable. Everything creative (spells, items, enemies, rules) is a plugin written against a narrow **plugin API**. Generated code may touch **only** that API.
4. **Plugins are Python.** LLMs write Python most reliably, and it matches the engine.
5. **Defense-in-depth sandbox for generated code:**
   - AST static checks: no imports, no dunder access, no `eval`/`exec`/`open`, only an allowlist of names
   - execution in a separate process with CPU-time and memory limits
   - only the plugin API is exposed
   - later, for a public deployment, a hosted sandbox
6. **The game never crashes because of agents.** If a plugin fails validation or at runtime, it is disabled and replaced with a safe fallback, and the player is told.
7. **Agents: a thin custom orchestrator on the Anthropic SDK**, with no heavy agent framework. Explicit orchestration is part of what the project demonstrates. Each agent has its own system prompt, its own context and structured (schema-validated) output.

### Agent roles

| Agent | Input | Output |
|---|---|---|
| Designer | player's natural-language idea + game state summary | mechanical spec (JSON): effects, numbers, targeting, duration, edge cases |
| Balancer | spec + current power level/abilities | approved/adjusted spec or rejection with reason (adversarial) |
| Coder | approved spec + plugin API docs | plugin source code |
| Tester | plugin code | runs static checks + headless simulations in the sandbox; pass or failure report fed back to the Coder (max N retries) |
| Dungeon Master (M4) | player behaviour stats | new enemy specs that counter the player's play style (goes through the same pipeline) |

## Planned layout

```
backend/
  spellforge/
    engine/      # grid, entities, turn loop, events, seeded RNG, plugin API
    plugins/     # hand-written builtin plugins (reference examples for the Coder agent)
    sandbox/     # AST validator + subprocess runner with limits
    agents/      # orchestrator + one module per agent role, prompts, schemas
    server/      # FastAPI + websocket
  tests/
frontend/        # TypeScript + Vite, canvas grid renderer
docs/            # design notes, eval results
```

## Milestones

- [ ] **M1: Engine (no AI).** Playable grid roguelike in the terminal/headless tests: player, walls, a hand-written enemy, turn loop, a plugin API with one hand-written spell plugin, deterministic tests. *Design the plugin API carefully, since everything else depends on it.*
- [ ] **M2: Web client.** FastAPI websocket server plus a minimal TS canvas renderer. Playable in the browser.
- [ ] **M3: One agent.** Invent box → a single LLM call writes a plugin → sandbox validation → hot-load → castable.
- [ ] **M4: Agent team.** Designer → Balancer → Coder → Tester with the retry loop and sandbox simulation. A Dungeon Master generates counter-enemies.
- [ ] **M5: Evals and launch.** Benchmark prompts; compare single agent vs. team on success rate, balance and cost/latency; README GIF; write-up.

## Current status

- 2026-09-17: repo scaffolded (README, CLAUDE.md, pyproject, package skeleton). **Next: start M1**, beginning with the plugin API design in `backend/spellforge/engine/`.

Keep this section up to date: when finishing a chunk of work, tick milestones and add a dated line saying what was done and what comes next.

## Conventions

- Python 3.11+, type hints everywhere, `dataclasses` for game state, `pytest` for tests, `ruff` for lint/format.
- The engine must be deterministic given a seed. Tests rely on this.
- Keep the plugin API small and documented. Its docstrings are fed to the Coder agent, so they are prompts too.
- Never execute generated code outside the sandbox, including in tests.
- Never commit API keys. Use `.env` (gitignored); `ANTHROPIC_API_KEY`.
- Commit in small, meaningful steps.

## Commands

```bash
# from backend/
python -m venv .venv && .venv/Scripts/activate   # Windows (Git Bash)
pip install -e ".[dev]"
pytest
ruff check . && ruff format .
```
