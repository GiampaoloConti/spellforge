# Plugin API design

Everything creative in Spellforge (spells, status effects, monsters) is a **plugin**: a
single Python source file written against a narrow API. Today the plugins are
hand-written. From M3 on, AI agents write them while the game is running. This note
explains the shape of that API and why it looks the way it does.

The source of truth is [`backend/spellforge/engine/api.py`](../backend/spellforge/engine/api.py)
and the `define_*` docstrings in [`plugins.py`](../backend/spellforge/engine/plugins.py).
Those docstrings are written as prompts because the Coder agent will read them.

## What a plugin looks like

```python
def on_cast(ctx, caster, target):
    origin = ctx.entity(caster).pos
    for pos in ctx.line(origin, target):
        if ctx.is_wall(pos):
            return
        victim = ctx.entity_at(pos)
        if victim is not None:
            ctx.damage(victim.id, 5, source=caster)
            return


define_spell(
    id="firebolt", name="Firebolt",
    description="Hurl a bolt of fire that deals 5 damage to the first creature in its path.",
    mana_cost=3, target="tile", range=7, on_cast=on_cast,
)
```

There are no imports. The loader runs the file in a namespace that holds only
`define_spell`, `define_status`, `define_monster`, `Pos`, `DIRECTIONS` and a short
allowlist of builtins (`len`, `min`, `sorted`, ...). The builtin plugins in
[`backend/spellforge/plugins/`](../backend/spellforge/plugins/) load the same way, so
they are valid few-shot examples for the Coder agent.

## Design rules

**1. Plain data crosses the boundary, never live objects.** Hooks receive entity *ids*
and `Pos` values. Queries return frozen `EntityView` snapshots. A plugin cannot reach
the engine's state, so it cannot corrupt it. The main payoff comes in M3: generated
code will run in a separate sandboxed process, and because every argument and return
value is plain data, `ctx` can become an RPC proxy without changing any plugin.

**2. Every change goes through `ctx`, and `ctx` validates everything.** Plugin code is
treated as untrusted input. Wrong types, NaN damage, unknown status ids and invalid
factions raise `PluginError` with a message written to be fed back to the Coder agent
("unknown status 'burn'; define it with define_status"). Dead or missing entity ids are
*not* errors. Generated code often acts on a creature that died a moment earlier, and
treating that as a no-op matches what the author meant.

**3. All randomness is seeded.** `ctx.random_int`, `ctx.chance` and `ctx.choice` draw
from the game's RNG, and plugins have no other randomness source. The same seed plus the
same inputs replays identically (`tests/test_determinism.py`). The Tester agent's
headless simulations will rely on this.

**4. A small set of hooks with exact timing rules.** Vague timing is where generated
code goes wrong, so the rules are explicit and tested:

| Hook | When |
|---|---|
| `spell.on_cast(ctx, caster, target)` | after the engine checks mana, cooldown, range and LOS |
| `status.on_apply(ctx, status)` | first application only (re-applying refreshes the duration) |
| `status.on_turn(ctx, status)` | start of each of the holder's turns, before it acts |
| `status.on_expire(ctx, status)` | duration ran out (not on death, not on `remove_status`) |
| `status.on_damaged(ctx, status, amount, source)` | holder took damage and survived |
| `status.on_death(ctx, status)` | holder died; still queryable with `alive == False` |
| `monster.act(ctx, me)` | each of the monster's turns, unless a status prevents acting |

A status with `duration=N` affects the holder's **next N turns**. It ticks at the end of
the holder's turns, not counting the turn in which it was applied or refreshed. So
"a sheep that explodes after 3 turns" is `prevents_action=True`, duration 3 and
`on_expire` → explode, which works with no off-by-one reasoning.

**5. The game never crashes because of a plugin.** Every hook call goes through one
choke point (`Game.call_hook`):

- any exception disables the owning plugin, removes its statuses from the board and emits
  `PLUGIN_DISABLED` with the reason. The round continues;
- each entity turn has a budget of `ctx` calls. A runaway loop is stopped, and the blame
  goes to the plugin that actually blew the budget, not to the innocent spell that
  triggered its hook. A hook that swallows the budget error with a bare `except:` is
  still caught;
- hook chains (thorns reflecting thorns) stop at a fixed depth and fizzle without disabling
  anything.

## Known limits (addressed by the sandbox in M3)

- `load_plugin` runs code in-process. It is for trusted, hand-written plugins only.
  Generated code must go through the sandbox, including in tests.
- The restricted builtins define the *contract*. They are not a security boundary. The
  sandbox adds AST checks (no imports, no dunder or underscore attribute access, no
  `eval`/`exec`/`open`), a separate process, and CPU and memory limits.
- The action budget counts API calls, not CPU. A pure-Python `while True: pass` needs the
  sandbox's CPU time limit.
- A plugin that fails halfway through a hook keeps the effects it already applied, with
  no rollback.
