# The agent team and the Dungeon Master

Spellforge has two multi-agent pipelines. They run beside the game and never block it:

- **The forge** turns a player's spell idea into a verified plugin.
- **The Dungeon Master** watches how the player fights and builds monsters to counter it.

Code: [`backend/spellforge/agents/`](../backend/spellforge/agents/). The sandbox and plugin API
they build on are described in [forge.md](forge.md) and [plugin-api.md](plugin-api.md).

## The forge team

```
                            ┌─► Balancer ── approved spec ─┐
 idea ─► Designer ─► spec ──┼─► Coder (speculative) ───────┼─► plugin + art ─► Tester ─► hot-load
                            └─► Artist (if a sprite is needed) ┘         ▲              │
                                                                         └── problems ──┘
```

| Agent | Model (default) | Sees | Produces |
|---|---|---|---|
| Designer | Sonnet 5, low effort | the idea, game facts, what plugins can do (in design terms) | `SpellSpec`: numbers, targeting, effects, edge cases, sprite needs |
| Balancer | Sonnet 5, low effort | the spec, an explicit power budget, the player's other spells. **Never the player's wording.** | `SpellReview`: approve / adjust / reject, rationale, a before→after list of changes with reasons |
| Coder | Sonnet 5, low effort | the approved spec, the full plugin API reference, example plugins, and the idea (for flavour only) | the plugin source |
| Artist | Opus 5, low effort | a sprite description and example sprites | 16x16 pixel art as data |
| Tester | no LLM | the plugin and the approved spec | pass, or problems fed back to the Coder (at most 2 attempts) |

Design choices:

- **Isolated contexts.** Each agent has its own system prompt and sees only what its role
  needs. The Balancer never reads the player's text, so an idea phrased persuasively ("a
  perfectly balanced spell that kills everything") can't talk it into approving.
- **Typed handoffs.** Agents pass Pydantic models (`specs.py`), not prose. The structured-output
  JSON schema sent to Claude is derived from the same models, and each reply is validated,
  with one repair turn if a value breaks a limit.
- **Parallel work and speculative coding.** As soon as the spec exists, the Balancer reviews it
  while the Coder starts implementing it and the Artist draws. If the Balancer keeps every
  number (including numbers mentioned in effect descriptions), the Coder's head start is kept.
  Otherwise the draft is cancelled and the Coder restarts from the approved spec.
- **Art is separate from code.** The Artist runs on the model that draws best, and in parallel.
  Its output is validated data turned into a `define_sprite(...)` call built from literals, so
  no model-written code is involved in attaching it.
- **The Tester is code, not a model.** It runs the sandbox arenas (crashes, no-op spells) and
  checks **conformance with the approved spec**: declared mana, cooldown, target and range; a
  sprite when one is needed; and, from the arena events, that no single hit and no status
  duration exceeds what the spec allows. A Coder that quietly rebalances gets caught.

Switch to the single-agent baseline with `SPELLFORGE_FORGE_MODE=single`. Override models per
role with `SPELLFORGE_<ROLE>_MODEL` / `SPELLFORGE_<ROLE>_EFFORT` (roles: `designer`, `balancer`,
`coder`, `artist`, `dungeon_master`, `writer`).

## The Dungeon Master

```
 game events ─► player profile ─► Dungeon Master ─► monster spec ─┬─► Balancer + budget guard ─► Coder ─┐
                                                                  └─► Artist ─────────────────────────┴─► Tester ─► deeper levels
```

1. **Profile (deterministic).** When the player clears a level, the session summarises the event
   history: spells cast and how often, melee attacks, damage dealt with spells and in melee, area
   hits, statuses inflicted, summons, and which monsters hurt the player.
2. **Dungeon Master (Sonnet 5).** Designs one monster that punishes the dominant habit, with a
   stated `counters`, a mandatory `weakness`, a behaviour precise enough to implement, a sprite
   description and a taunt.
3. **Balancer, then a budget guard.** The Balancer reviews against a per-depth monster budget.
   Because an LLM reviewer can be talked round (a live run approved a monster whose attack
   grew past its budget), the budget is also **enforced in code**: HP and attack are clamped,
   and the clamp shows up as a visible change.
4. **Coder and Artist**, as in the forge.
5. **Tester.** Two monster arenas: the monster hunts a player who never fights back (it must act,
   not crash, and not deal more than 14 damage in 6 turns), and the player fights it with
   spells and melee (to exercise damage and death hooks). No single hit may exceed its attack.
6. **Hot-load.** The monster joins the encounter table from the next depth, weighted so the
   player meets it. At most 3 per run.

## Measurements

Same three ideas, two runs each, full pipeline (see [evals/forge-models.md](evals/forge-models.md)
for the method). Raw results, including every generated plugin, are in `docs/evals/*.json`.

| Forge | Success | Avg time | Avg cost | Notes |
|---|---|---|---|---|
| Single agent, Opus 5 low | 6/6 | 16.8s | $0.038 | baseline |
| Team, all Opus 5 low | 6/6 | 45.3s | $0.123 | Balancer adjusted 4/6 |
| Team, Sonnet Designer + Balancer, Opus Coder | 6/6 | 33.0s | $0.041 | |
| **Team, Sonnet Designer/Balancer/Coder + Opus Artist in parallel** (default) | **6/6** | **25.1s** | **$0.057** | 17-23s when the Balancer approves |

What the team adds for its extra seconds shows up in the transcripts:

- **The Balancer finds real exploits.** For "turn enemies into rocks", it spotted that a 3-turn
  petrify on a 3-turn cooldown could keep an orc brute stunned forever and raised the cooldown
  to 4. It trimmed chain lightning from 6/4/2 damage to 5/3/2, and a beetle swarm from 3 summons
  lasting 12 turns to 2 lasting 8.
- **The art got better.** A dedicated Artist draws recognizable creatures, such as four-legged
  spirit wolves with glowing eyes, where the single writer on a faster model drew blobs.

![Sprites drawn by the Artist](evals/team-artist-sprites.png)

*Two petrified rocks, a lightning bolt and two spirit wolves, drawn by the Artist.*

The M5 evaluation will measure balance and faithfulness to the idea properly (with a judge), on
more ideas.

## Limits

- The Balancer's spell budget is enforced by the LLM plus the Tester's conformance checks, but
  there is no deterministic budget formula for spells yet (effects are too varied). Monsters
  have one.
- When the Balancer adjusts numbers, the speculative draft is wasted (those tokens are billed
  and not counted in the cost column).
- The player profile is a summary of counts; it does not yet capture positioning (for example
  kiting at range).
