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
| Artist (added in M4) | sprite description | 16x16 pixel art data, drawn in parallel with the Balancer and Coder |
| Dungeon Master (M4) | player behaviour stats | new enemy specs that counter the player's play style (goes through the same pipeline) |

## Planned layout

```
backend/
  spellforge/
    engine/      # grid, entities, turn loop, events, seeded RNG, plugin API
    plugins/     # hand-written builtin plugins: plugin source loaded via load_plugin, not imported
    sandbox/     # AST validator + per-plugin subprocess (ctx over JSON-line RPC), limits
    agents/      # orchestrator + one module per agent role, prompts, schemas
    server/      # FastAPI + websocket
  tests/
frontend/        # TypeScript + Vite, canvas grid renderer
docs/            # design notes, eval results
```

## Milestones

- [x] **M1: Engine (no AI).** Playable grid roguelike in the terminal/headless tests: player, walls, a hand-written enemy, turn loop, a plugin API with one hand-written spell plugin, deterministic tests. *Design the plugin API carefully, since everything else depends on it.*
- [x] **M2: Web client.** FastAPI websocket server plus a minimal TS canvas renderer. Playable in the browser.
- [x] **M3: One agent.** Invent box → a single LLM call writes a plugin → sandbox validation → hot-load → castable.
- [x] **M4: Agent team.** Designer → Balancer → Coder → Tester with the retry loop and sandbox simulation. A Dungeon Master generates counter-enemies.
- [x] **M5: Playable by friends.** Hosted on Hugging Face Spaces from GitHub with the Anthropic key as a Space secret (never in the repo), an invite code and a daily spending cap; UI redesign (full-height board, dock, pixel sigil); the Arcane Forge needs an arcane shard found every 3 levels; measured balance (probe arena + rebalance loop).
- [ ] **M6: Evals and launch.** Benchmark prompts; compare single agent vs. team on success rate, balance and cost/latency; README GIF; write-up.

## Current status

- 2026-09-17: repo scaffolded (README, CLAUDE.md, pyproject, package skeleton).
- 2026-09-17: **M1 done.** Engine in `backend/spellforge/engine/`: `api.py` (plugin contract: `Ctx`, views, hooks), `plugins.py` (loader + `Registry`), `game.py` (turn loop, combat, statuses, hook dispatch with disable-on-failure, action budget, hook depth limit), `context.py` (validating `Ctx` impl). Builtin plugins (`goblin`, `firebolt`, `frost_nova`) are plugin *source* loaded like generated code. Terminal client: `python -m spellforge`. 79 tests. Design notes: `docs/plugin-api.md`. **Next: M2**: FastAPI websocket server (send `Game.snapshot()` + events, receive actions) and a minimal TS canvas renderer.
- 2026-09-17: **M2 done.** `backend/spellforge/server/`: `protocol.py` (pydantic client messages, state/error replies), `session.py` (`GameSession`, network-free), `app.py` (one session per `/ws` connection; serves `frontend/dist` if built). `narration.py` (events → log text) shared by CLI and server. Frontend: Vite + TS, no framework: `protocol.ts` (mirrors server), `grid.ts` (range/LOS hints, same Bresenham as engine), `input.ts`, `renderer.ts` (canvas), `effects.ts`, `ui.ts`, `main.ts`. Verified end to end in headless Edge via DevTools (keys, targeting, casting, overlay). Protocol doc: `docs/protocol.md`. **Next: M3**: invent box in the UI → single LLM call writes a plugin → sandbox (AST validator + subprocess with limits, `ctx` as RPC proxy) → hot-load → castable. Needs server-pushed messages (`forge_progress`) while the game stays playable.
- 2026-09-17: Pixel-art sprites replace ASCII glyphs in the browser. Art is plain data in `frontend/src/art.ts` (16x16 grids of palette chars, one palette per sprite), validated by `pixelart.ts` tests, rasterised and cached by `atlas.ts`. Renderer uses integer zoom (crisp pixels) with a camera following the player, idle bob, facing, shadows, frozen tint; unknown creature kinds fall back to their glyph. Idea for M4: the Dungeon Master can emit sprite grids in the same format for generated monsters.
- 2026-09-17: **M3 done.** `sandbox/`: `validator.py` (AST allowlist), `worker.py` + `host.py` (one isolated process per plugin, hooks are proxies, ctx calls are JSON-line RPC incl. nested hooks; 1s per-message timeout; Windows Job Object / RLIMIT_AS memory cap; empty env). `agents/`: `api_docs.py` (API reference generated from docstrings), `spell_writer.py` (claude-opus-5, adaptive thinking, structured output, `fallbacks: "default"`, cached system prompt with builtin plugins as examples), `verify.py` (static → sandbox load → rules → test-arena casts), `forge.py` (write → verify → feedback, max 2 attempts), `try_forge.py` CLI. Server: `invent` message, pushed `welcome`/`forge` updates, forge runs as a background task while play continues, hot-load via a session-owned sandbox. Frontend: Arcane Forge panel (`forge.ts`). Live: chain lightning forged in ~15s, first attempt, ~8k tokens, cast in-game. Docs: `docs/forge.md`. 147 backend + 20 frontend tests. Known gap: no filesystem/network isolation for plugin processes (same OS user). **Next: M4**: split the writer into Designer → Balancer → Coder → Tester with isolated contexts and schema-validated handoffs; reuse `verify.py` as the Tester's sandbox runs; Dungeon Master generating counter-enemies (monster plugins + sprite grids). Keep the M3 writer as the single-agent baseline for M5 evals.
- 2026-09-17: **Playtest fixes.** (1) Endless dungeon: killing the last enemy opens stairs (`>`) on the farthest tile; stepping on them generates depth+1 (heal 5, full mana); `builtin_encounters(depth)` in `plugins/__init__.py` scales monster mix/count; the forge keeps running across levels. (2) Five new monster plugins with AI and art: bat, skeleton_archer, slime (+slimeling, split via on_death status), orc, goblin_shaman. (3) Plugin sprites: `define_sprite`, `define_status(appearance=)`, `define_monster(sprite=)`; snapshot `appearance`/`can_act`; server sends sprite art incrementally; goblin art moved into its plugin; writer must draw sprites for transformations (enforced by `forge.changes_appearance`). `define_sprite` forgives off-by-one rows. (4) Speed: `agents/bench_forge.py` benchmark → default Opus 5 effort `low` (27s → ~17s, same quality; Sonnet 5 ~12s but weaker art), see `docs/evals/forge-models.md`; writer streams progress notes. Live check: "turn enemies into rocks" forged in 16s and a bat became a rock sprite in-game. 180 backend + 20 frontend tests.
- 2026-09-17: **M4 done.** See `docs/agents.md`. `agents/specs.py` (Pydantic handoffs + derived structured-output schemas), `llm.py` (shared streamed structured/validated calls, usage/cost, per-role model defaults: Sonnet 5 low for designer/balancer/coder/DM, Opus 5 low for artist and single writer), `designer.py`, `balancer.py` (adversarial budget review; `enforce_monster_budget` clamps in code), `coder.py`, `artist.py` (art as validated data -> literal `define_sprite`), `tester.py` (deterministic: sandbox arenas + spec conformance: declared stats, max hit/duration, sprite, monster hit <= attack), `team.py` (`TeamForge`: Coder + Artist start in parallel with the Balancer; speculative draft kept if numbers survive), `dungeon_master.py` (event-history profile -> DM agent -> Balancer -> Coder + Artist -> monster arenas), `factory.py`, `forge.py` (`SpellForge` protocol; `SingleAgentForge` baseline via `SPELLFORGE_FORGE_MODE=single`). Session triggers the DM on level clear; counter monsters join encounters from depth+1 (weight 5, max 3/run). UI: `pipeline.ts` live agent steps with Balancer verdict/changes, per-agent cost table, `dungeonMaster.ts` card. Dev tools (`SPELLFORGE_DEV_TOOLS=1`, `window.spellforgeDev("clear_level"|"descend")`) for demos/automated checks. Benchmarks: single 16.8s/$0.038; team default 25.1s/$0.057 (17-23s when approved), all 6/6. Verified live in headless Edge (forge team, DM, counter monster at depth 2). 201 backend + 20 frontend tests. **Next: M5**: eval suite (more ideas, LLM judge for balance/faithfulness, single vs team), README GIF (use dev tools), write-up.

- 2026-09-17: **M5 done** (redefined by the owner: deploy for friends, UI, forge gating, balance). (1) Balance: `agents/budget.py` limits by mana/cooldown; `verify.probe_spell` casts each spell among training dummies (caster at 2 HP) and measures damage, healing, skipped enemy turns, summoned HP, reach; over budget → `TeamForge` sends measurements back to the Balancer once (approve again = error); `Effect` needs absolute amounts; Tester checks heal size. (2) Arcane shards: `Game.items`/`inventory`, shard on depths 1, 4, 7… (`has_shard`), picked up by stepping on it; the session spends one per forge and refunds on failure; dev command `give_shard`. (3) UI: full-height board, dock with HP/mana/shards/hotbar and log, right column only Forge + DM, controls in a `?` popover, pixel-art anvil sigil (also favicon) + Pixelify Sans wordmark, flat pixel styling. (4) Deployment: `server/limits.py` (`AccessGate` with `locked`/`unlock` handshake, `SpendingCap` reserve/settle, `SessionSlots`), `sandbox/hardening.py` (Linux: server non-dumpable; workers: RLIMIT_AS/NPROC/FSIZE/CORE, network namespace where allowed), root `Dockerfile` (built and run-tested in WSL Docker: unlock, sandbox, /proc environ protection), `.github/workflows/ci.yml` (tests, then force-push to the Space with `deploy/huggingface/README.md`), step-by-step `docs/deploy.md`, frontend `gate.ts`. Backend suite also runs green on Linux (WSL). 230 backend + 22 frontend tests. **Next: M6**: owner completes the HF/GitHub setup in `docs/deploy.md`; then the eval suite (single vs team, LLM judge for balance/faithfulness), README GIF, write-up.
- 2026-09-17: Owner deployed on Hugging Face (PRO; Docker Spaces are no longer free). Friend-feedback changes: (1) the Dungeon Master runs on every second cleared level (`DUNGEON_MASTER_EVERY = 2` in `session.py`: depths 2, 4, 6…). (2) Leaderboard: `server/leaderboard.py` (best run per player keyed by a browser-generated id, not IP; ranking depth → kills → fewer turns; JSON file under `SPELLFORGE_DATA_DIR`, on HF a Storage Bucket mounted at `/data`; in memory when unset), engine `Game.kills`, protocol `identify`/`set_name` → `leaderboard` pushed on death (dev-tool runs not recorded), frontend `leaderboard.ts` (table and name form on the death screen). Owner must attach a bucket at `/data` (used automatically; docs/deploy.md step 5). **Next: M6** evals.

- 2026-09-18: **Playtest bugfixes + UX pass (friends' feedback).**
  - **Forge resilience:** `agents/llm.py` `structured_call` now retries transient API failures (a mid-stream `error` SSE surfaces as `APIStatusError` with `status_code == 200` — the SDK's own retries only cover the initial request, not mid-stream). Retries statuses `{200,500,502,503,529}` + `APIConnectionError`, up to `RETRY_ATTEMPTS = 3` with linear backoff. This was the cause of the "the Balancer's API call failed (200)" report. Test: `tests/test_llm.py` (builds a fake `APIStatusError` subclass — must NOT import `httpx`; it isn't installed in CI).
  - **Minion despawn bug (root cause + fix):** there was no clean way to remove a summon, so generated code killed it with huge damage, tripping the `MAX_AMOUNT` (1000) cap → `PluginError` → plugin disabled → minion stuck. Added `ctx.despawn(entity_id)` to the plugin API (`engine/api.py` abstractmethod + docstring, implemented in `engine/context.py`). Scoped to **summoned** creatures only (`Entity.summoned` flag set in `game.spawn`) so it can't instant-delete natural enemies (balance hole). Auto-flows to the sandbox allowlist and Coder docs (both derive from `Ctx.__abstractmethods__`). Test: `tests/test_despawn.py`.
  - **Dungeon Master doesn't restart:** it runs unattended with no retry, so one error silently skipped that level's counter-monster. Added a bounded retry `DUNGEON_MASTER_ATTEMPTS = 2` in `server/session.py` `_run_dungeon_master`.
  - **Frontend features (all shipped, `npm run build` + 22 vitest pass):** soundtrack (moved the owner's file to `frontend/public/soundtrack.mp3`; `src/sound.ts` loops it, starts on first gesture, mute button `#mute`); minimap (`src/minimap.ts`, `#minimap` canvas — purple = player, gold = stairs, read from `state.map`); first-run tutorial (`src/tutorial.ts`, shown only when `storedName()` is empty = returning-browser gate); start-screen name prompt (`src/intro.ts`); dev toggle (`#dev-toggle` switch in the topbar → `document.body.dataset.mode`; **player** mode = default = a themed loading bar `.forge-progress`, hides `.pipeline`/`.forge-code`/`.forge-meta`; **dev** mode = full agent pipeline). Wiring in `src/main.ts` (`startFlow()` runs intro→tutorial once, `greeted` guard for reconnects; `setupDevToggle()`; minimap drawn in `refresh()`). `src/leaderboard.ts` gained `rememberName()`. Styles appended to `src/style.css`. NOTE: this project has `erasableSyntaxOnly` on — do NOT use constructor parameter properties (`constructor(private x)`); declare fields explicitly.
  - **Deploy:** `.github/workflows/ci.yml` deploy step now LFS-tracks `*.mp3` for the Space commit only (`git lfs install --local` + `git lfs track` + `git add --renormalize .`), because Hugging Face rejects raw binaries (wants LFS/Xet). The GitHub repo keeps the mp3 as a normal file. `frontend/dist/` is gitignored; the Space's `Dockerfile` rebuilds the frontend from source, so **all frontend source files must be committed** for changes to appear.

- 2026-09-18: **Polish.** Player mode no longer names the agents: `pipeline.stageMessage(stage, message)` swaps the server note for a line of flavour per stage (dev mode still shows the note); used by `forge.ts` and `dungeonMaster.ts`. Monsters walk instead of teleporting: `renderer.ts` keeps `lastPos`/`steps` and interpolates a 120ms slide (`STEP_MS`, adjacent tiles only, so blinks stay instant), `renderer.animating` keeps `main.ts` asking for frames.

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
python -m spellforge            # terminal client
python -m spellforge.server     # http://127.0.0.1:8000 (serves frontend/dist if built)

# from frontend/
npm install
npm run dev                     # http://localhost:5173, proxies /ws and /api to :8000
npm test                        # vitest
npm run build                   # tsc typecheck + vite build into frontend/dist
```
