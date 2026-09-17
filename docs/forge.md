# The forge: from a player's idea to a running spell

The player types an idea into the Arcane Forge. A few seconds later the spell is in their
spellbook. This note covers what happens in between: the agent, the sandbox and the
checks between them. M3 uses a single agent; M4 replaces it with a team.

```
 idea ──► Spell Writer (Claude) ──► static checks ──► sandbox load ──► test arenas ──► hot-load
               ▲                                                            │
               └─────────────── problems fed back (max 2 attempts) ─────────┘
```

Code: [`backend/spellforge/agents/`](../backend/spellforge/agents/) and
[`backend/spellforge/sandbox/`](../backend/spellforge/sandbox/).

## The Spell Writer (`agents/spell_writer.py`)

One call to `claude-opus-5` with adaptive thinking and structured output
(`{notes, spell_id, plugin_source}`), streamed. The system prompt is stable and cached:

- **Game facts**: player and goblin stats, and the built-in spells as a balance reference.
- **Rules**: one spell, fresh ids, robust against creatures dying mid-effect.
- **Plugin API reference**, generated from the engine's docstrings by
  `agents/api_docs.py`, so the agent's documentation can't drift from the code.
- **The built-in plugins as examples**. They are loaded exactly like generated code, so
  they are valid few-shot examples.

The player's text goes in `<idea>` tags in the user turn and is treated as a design
request only. If verification fails, the forge appends the model's full previous response
and the list of problems, then asks for a corrected plugin. Refusals fall back server-side
(`fallbacks: "default"`).

Try it without the UI (this uses real tokens):

```bash
python -m spellforge.agents.try_forge "a spell that turns enemies into sheep that explode"
```

## Verification (`agents/verify.py`)

1. **Static checks** (`sandbox/validator.py`): no imports, classes, async code, `global`,
   generators, `with`, private or dunder attributes, `str.format`, or names outside the
   plugin API and safe builtins.
2. **Sandbox load**: runs the `define_*` validation for types and ranges.
3. **Game rules**: exactly one spell, no id clashes, mana cost affordable (1-10).
4. **Test arenas**: cast the spell in a small map at the nearest enemy, a farther enemy and
   an empty floor tile (for tile spells), then play 3 rounds. Any plugin error is a problem
   sent back to the agent. A spell whose cast round matches a plain wait round gets a
   "no visible effect" warning. The engine is deterministic, so that comparison is exact.

## The sandbox (`sandbox/`)

Each plugin runs in its own Python process: `worker.py` runs the plugin, and `host.py`
runs in the game server and talks to it. Hooks in the engine are proxies. When a hook
fires, the host sends the call to the worker, and the plugin's `ctx.*` calls come back as
JSON-line requests that the host runs against the real game. This is possible because the
plugin API only passes plain data.

Defense in depth:

| Layer | What it stops |
|---|---|
| AST validator (host and worker) | reaching Python internals, imports, format-string attribute tricks |
| Restricted namespace | anything but the API and safe builtins |
| Separate process, `python -I`, empty environment, temp working directory | crashes taking down the game, API keys leaking into plugin code |
| Job Object on Windows / `RLIMIT_AS` on POSIX | memory bombs (256 MB cap), child processes |
| Per-message timeout (1s) | infinite loops: the process is killed |
| Engine action budget and hook depth limit | runaway `ctx` calls, infinite reaction chains |
| Host re-validates the worker's definitions | a compromised worker registering invalid content |
| API misuse disables the plugin even if caught | plugins hiding their errors |

**Not covered yet (needed before a public deployment):** filesystem and network isolation.
The worker runs as the same OS user as the server. A hosted sandbox or container per
session would close this gap.

## In the game (`server/session.py`)

The forge runs as a background task. The player keeps playing while it works, and progress
is pushed over the websocket (`forge` messages). When the spell passes, a fresh sandbox
process is started for the live game, the plugin is added to the game's registry, and the
player learns the spell. The limits are one forge at a time and 6 forged spells per run.
Starting a new game cancels the forge and kills the plugin processes.

## First measurements

The M5 eval suite will measure these properly. Early live runs, at effort `high`:

| Idea | Attempts | Time | Tokens |
|---|---|---|---|
| "a spell that turns enemies into sheep, but they explode after 3 turns" | 1 | 25.6s | 8.5k |
| "chain lightning that jumps between up to 3 enemies, weaker with each jump" | 1 | 14.7s | 7.8k |
| (same idea, second run) | 1 | 15.9s | 8.0k |
