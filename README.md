# Spellforge

**A roguelike where you invent the spells, and a team of AI agents writes them into the game while you play.**

> "A spell that turns enemies into sheep, but they explode after 3 turns."

You type it. A multi-agent pipeline designs it, balances it, writes it as code, tests it in a sandbox and hot-loads it into the running game. A few seconds later, you cast it.

🚧 **Work in progress.** See the roadmap below.

## How it works

```
 your idea ──► Designer ──► Balancer ──► Coder ──► Tester ──► hot-loaded into the game
                 spec      nerfs broken   plugin    sandbox sim
                           ideas          code      ↺ retries on failure
```

- **Deterministic engine, generated content.** A small hand-written Python engine runs the game. Everything creative is a plugin written by agents against a narrow plugin API.
- **Agents never block the game.** They work between turns, and the game stays playable.
- **Generated code is sandboxed.** It goes through static AST checks, then runs in an isolated process with resource limits and access to the plugin API only.
- **Nothing crashes the game.** Plugins that fail are disabled and replaced with safe fallbacks.
- **Measured, not claimed.** An eval suite compares a single agent against the agent team on success rate, game balance, cost and latency.

## Stack

Python (engine, agents, sandbox, FastAPI websocket server) · TypeScript (canvas renderer) · Claude (Anthropic API)

## Roadmap

- [ ] M1: Deterministic grid engine plus plugin API
- [ ] M2: Browser client
- [ ] M3: Single agent writes plugins at runtime
- [ ] M4: Agent team (designer, balancer, coder, tester) plus a Dungeon Master that counters your play style
- [ ] M5: Evals (single agent vs. team) and demo
