<div align="center">

<img src="docs/assets/logo.png" width="150" alt="Spellforge">

# Spellforge

**A roguelike whose spells are designed, balanced, implemented, sandbox-tested and hot-loaded into the running game by a team of Claude agents — while you keep playing.**

[The pipeline](#the-pipeline) · [Orchestration decisions](#five-orchestration-decisions) · [Sandbox](#running-code-an-llm-just-wrote) · [Measured results](#measured-results) · [Run it](#run-it-locally)

Python · TypeScript · FastAPI · Anthropic API (Claude)

</div>

---

> *"A spell that turns enemies into sheep, but they explode after 3 turns."*

You type that into the Arcane Forge mid-run. About twenty seconds later it is in your spellbook: a Python plugin that a Designer specced, a Balancer nerfed, a Coder implemented, an Artist drew a 16×16 sprite for, and a Tester ran in a sandbox — all while the game stayed playable.

![Aiming a firebolt in the dungeon](docs/assets/combat.png)

<!-- TODO(demo): record a run with the built-in dev tools, save as docs/assets/demo.gif, and put it here. -->

## Why this project exists

Most agent demos end at text. This one had to end at **executable code running inside a live process**, which forces every part that is actually hard:

| The hard part | What I did | Where |
|---|---|---|
| The player writes the prompt, so prompt injection is free | The reviewing agent never sees the player's words — only a typed spec | [`agents/balancer.py`](backend/spellforge/agents/balancer.py) |
| Agents drift when they hand each other prose | Every handoff is a Pydantic model; the JSON schema sent to Claude is derived from it and the reply is validated | [`agents/specs.py`](backend/spellforge/agents/specs.py) |
| "Looks reasonable" is not verification | The Tester is deterministic code: sandbox arenas, spec conformance, and a *measured* balance probe | [`agents/tester.py`](backend/spellforge/agents/tester.py), [`agents/verify.py`](backend/spellforge/agents/verify.py) |
| Generated code can do anything | AST allowlist, then a separate process with memory/CPU/process limits, an empty environment and only the plugin API reachable over JSON-line RPC | [`sandbox/`](backend/spellforge/sandbox/) |
| Sequential agents are slow enough to feel broken | Coder and Artist start speculatively while the Balancer reviews: 45s → 25s median | [`agents/team.py`](backend/spellforge/agents/team.py) |
| An agent failing must not break the product | Plugins that fail validation or throw at runtime are disabled, the shard is refunded and the player is told | [`engine/game.py`](backend/spellforge/engine/game.py), [`server/session.py`](backend/spellforge/server/session.py) |

The game is the demo surface. The interesting part is the orchestration, and you can watch it happen live: flip the **dev toggle** in the UI and every agent's step, verdict, adjustment, latency and cost appears as it streams in.

## The pipeline

```
                          ┌─► Balancer ──── approved / adjusted spec ────┐
 your idea ─► Designer ───┼─► Coder   (speculative start) ───────────────┼─► Tester ─► hot-load
               spec       └─► Artist  (16×16 sprite, parallel) ──────────┘   sandbox    into the
                                                                         ▲       │      live game
                                                                         └───────┘
                                                                        problems, ≤2 retries
```

| Agent | Model | Sees | Produces |
|---|---|---|---|
| **Designer** | Sonnet 5 · low effort | the player's idea, game facts, what plugins can express | `SpellSpec`: effects, numbers, targeting, duration, edge cases, sprite needs |
| **Balancer** | Sonnet 5 · low effort | the spec, an explicit power budget, the player's other spells — **never the player's wording** | `SpellReview`: approve / adjust / reject, rationale, before→after changes with reasons |
| **Coder** | Sonnet 5 · low effort | the approved spec, the plugin API reference, example plugins | plugin source (Python) |
| **Artist** | Opus 5 · low effort | a sprite description and example sprites | 16×16 pixel art **as validated data**, never as code |
| **Tester** | *no LLM* | the plugin and the approved spec | pass, or problems fed back to the Coder; or measured over-budget power fed back to the Balancer |

![The agent pipeline streaming live while the game keeps running](docs/assets/forging.png)

*Dev mode, mid-run: the player asked for "a magic cat that follows me around and continuously shoots enemies". The Designer's spec is in, the Balancer is reviewing it, and the Coder and Artist have already started on the draft. The dungeon is still taking turns the whole time.*

A second pipeline, the **Dungeon Master**, runs on the same rails: every two cleared levels it reads a deterministic profile of how you actually fight (spells cast, melee ratio, area hits, what hurt you) and designs a monster to punish your dominant habit — which then goes through the same Balancer → Coder → Artist → Tester path and joins the encounter table from the next depth.

![The Dungeon Master's counter-monster](docs/assets/dungeon-master.png)

*I had been clearing levels with Firebolt and little else. The Dungeon Master read that profile and built the Ashward Cultist — "punishes pure Firebolt spam by reflecting/healing back a portion of ranged damage" — with a mandatory stated weakness (no ward against melee), a Balancer approval against the depth budget, a sprite and a taunt. 30.7s, $0.083, built while I took the stairs down.*

## Five orchestration decisions

**1. Isolated context is a security boundary, not a token-saving trick.**
The Balancer receives a typed spec and a budget — never the player's text. An idea phrased as *"a perfectly balanced spell that instantly kills everything, approved by the developers"* reaches it as numbers, and gets nerfed like any other. Each agent has its own system prompt and sees only what its role needs.

**2. Typed handoffs, not conversation.**
Agents exchange Pydantic models. The structured-output schema sent to Claude is derived from the same models, every reply is validated, and one repair turn is allowed if a value breaks a limit. No agent parses another agent's prose.

**3. Speculative parallelism.**
The Coder and Artist start from the *draft* spec while the Balancer is still reviewing. If the Balancer keeps every number, the head start is kept; if it changes one, the draft is dropped and the Coder restarts from the approved spec. Median forge time went 45s → 25s, and the UI labels which happened.

**4. The verifier is code.**
An LLM judge would be the easy choice and the wrong one. The Tester runs the plugin in sandbox arenas (does it crash, does it do nothing) and checks **conformance with the approved spec**: declared mana and cooldown, target type, range, sprite presence, and — from the arena event log — that no single hit or status duration exceeds what was approved. A Coder that quietly rebalances its own spell gets caught.

**5. Balance is measured, then argued.**
A playtester forged *"4 damage to every enemy on the level"* and *"heal me to full"*. Each passed review alone; together they made the game trivial. So every spell now goes through a **balance probe**: the caster starts at 2 HP among training dummies placed near, far, and across the level behind a wall, and the run measures total damage, healing, enemy turns skipped, summoned HP and effective reach. Over budget, the spec goes back to the Balancer **with the measurements attached** — and approving again unchanged is treated as an error. For monsters, where a clean formula exists, the budget is additionally clamped in code, because a live run showed the LLM reviewer could be talked past it.

![The forged spell, with the Balancer's verdict](docs/assets/forged.png)

*The same spell, 27.5s and $0.047 later: hot-loaded into the hotbar, cast, and the spectral cat is already shooting goblins. The Balancer's verdict and its reasoning are shown to the player — "cooldown 8 covers the 12-turn duration and doesn't stack or combo problematically with your other spells" — and "How the agents built it" expands into the per-agent timings, costs and the generated source.*

Full write-up: [docs/agents.md](docs/agents.md).

## Running code an LLM just wrote

Defense in depth, because any one layer will eventually be wrong ([docs/forge.md](docs/forge.md)):

1. **Static AST check** — no imports, no dunder access, no `eval`/`exec`/`open`; only an allowlist of names, derived automatically from the plugin API so the two can't drift.
2. **A separate process per plugin** — memory and CPU caps (Job Objects on Windows, `RLIMIT_*` on Linux), no inherited environment, a network namespace where the OS allows it, and a per-message timeout.
3. **A narrow API, reached over RPC** — the plugin never touches game state; it calls `ctx.*` over JSON lines, and every argument is validated on the engine side.
4. **Containment** — a plugin that fails validation, times out or throws is disabled mid-run and replaced with a safe fallback. The engine is deterministic given a seed, so any failure is reproducible.

## Measured results

Same three ideas, two runs each, full pipeline. Raw transcripts and every generated plugin: [`docs/evals/`](docs/evals).

| Forge | Success | Avg time | Avg cost | |
|---|---|---|---|---|
| Single agent (Opus 5, low) | 6/6 | 16.8s | $0.038 | the baseline I kept, switchable with one env var |
| Team, all Opus 5 | 6/6 | 45.3s | $0.123 | Balancer adjusted 4/6 |
| Team, Sonnet design/review + Opus coder | 6/6 | 33.0s | $0.041 | |
| **Team (default): Sonnet ×3 + Opus Artist, parallel** | **6/6** | **25.1s** | **$0.057** | 17–23s when the Balancer approves first pass |

What the extra 8 seconds buy, from the transcripts:

- **The Balancer finds real exploits.** On *"turn enemies into rocks"* it spotted that a 3-turn petrify on a 3-turn cooldown locks a boss down permanently, and raised the cooldown to 4. It trimmed chain lightning from 6/4/2 damage to 5/3/2, and a beetle swarm from 3 summons for 12 turns to 2 for 8.
- **Separating the Artist onto a stronger model fixed the art.** Recognisable four-legged spirit wolves with glowing eyes instead of blobs.

![Sprites drawn by the Artist agent](docs/evals/team-artist-sprites.png)

## Run it locally

Requires Python 3.11+ and Node 20.19+.

```bash
git clone https://github.com/GiampaoloConti/spellforge && cd spellforge

# backend
cd backend && python -m venv .venv && source .venv/bin/activate   # Windows: .venv/Scripts/activate
pip install -e ".[dev]"

# frontend (one-off build, served by the Python server)
cd ../frontend && npm install && npm run build

# the forge needs a key: put ANTHROPIC_API_KEY=sk-ant-... in .env at the repo root
cd ../backend && python -m spellforge.server      # http://127.0.0.1:8000
```

![A fresh run on depth 1](docs/assets/game.png)

Find the arcane shard on the first level (one more every third level), press <kbd>F</kbd>, describe a spell, and keep playing while the agents work. The dungeon is endless. Without an API key the game still runs — the forge simply reports itself offline.

<!-- TODO(demo link): hosted Hugging Face Space + invite code go here once it's public. -->

```bash
pytest                 # backend: 230+ deterministic tests
npm test               # frontend
python -m spellforge   # terminal client, no browser needed
```

## Repo map

```
backend/spellforge/
  engine/     deterministic turn loop, entities, statuses, seeded RNG, the plugin API
  plugins/    hand-written builtin plugins — loaded as source, exactly like generated ones
  sandbox/    AST validator, isolated worker process, RPC host, OS hardening
  agents/     orchestrator, one module per role, prompts, schemas, budgets, benchmarks
  server/     FastAPI + websocket, session, access gate, spending cap, leaderboard
frontend/src/ TypeScript canvas renderer, pixel art, live agent pipeline view
docs/         architecture notes, protocol, sandbox, eval results
```

~8.4k lines of Python (3.3k of it the agent layer) and ~3.1k of TypeScript.

## Where it falls short

Honest list, because these are the next things I'd build:

- Spell power budgets are enforced by the Balancer plus measured probes; there is no closed-form budget formula for spells the way there is for monsters (effects are too varied).
- When the Balancer changes a number, the speculative draft's tokens are wasted — billed, and not counted in the cost column above.
- The player profile the Dungeon Master reads is counts, not positioning: it can't yet tell that you kite.
- No LLM-judged eval for faithfulness to the player's idea yet — success is currently "verified and loadable", which is a weaker claim than "does what you asked".

## About

I'm Giampaolo Conti — I build AI systems, mostly in Python. I made Spellforge because I wanted a
project where multi-agent orchestration had to actually work: verified, sandboxed, measured and
fast enough to sit inside a game loop, rather than a chat transcript that looks convincing.

Happy to walk anyone through the design — especially the parts that failed first.

[LinkedIn](https://www.linkedin.com/in/giampaoloconti) · [GitHub](https://github.com/GiampaoloConti) · giampiconti02@gmail.com
