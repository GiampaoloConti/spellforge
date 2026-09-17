# Client ↔ server protocol

The browser and the Python server talk over one websocket at `/ws`, using JSON
messages. The server is authoritative: the client sends *intents* and draws whatever
state comes back. Each connection owns its own game.

Sources of truth: [`backend/spellforge/server/protocol.py`](../backend/spellforge/server/protocol.py)
(pydantic models) and [`frontend/src/protocol.ts`](../frontend/src/protocol.ts) (TypeScript
types). Keep them in sync.

## Client → server

```jsonc
{ "type": "unlock", "code": "invite-code" }  // only when the server sent "locked"
{ "type": "new_game", "seed": 42 }          // seed optional (null = random)
{ "type": "action", "action": { "kind": "move", "dx": 1, "dy": -1 } }   // dx, dy in -1..1
{ "type": "action", "action": { "kind": "wait" } }
{ "type": "action", "action": { "kind": "cast", "spell": "firebolt", "target": [12, 5] } }
{ "type": "action", "action": { "kind": "cast", "spell": "frost_nova", "target": null } }
{ "type": "invent", "idea": "chain lightning that jumps between 3 enemies" }   // 3-300 chars
{ "type": "dev", "command": "clear_level" | "descend" | "give_shard" }   // SPELLFORGE_DEV_TOOLS=1
```

Messages are validated strictly: unknown fields, out-of-range values and messages over
4 KB are rejected with an `error` reply before they reach the engine.

## Server → client

`new_game` and `action` get exactly one reply (`state` or `error`). The server also pushes
`welcome` on connect, and `forge` and `dungeon_master` updates at any time.

When `SPELLFORGE_ACCESS_CODE` is set, a connection first gets
`{ "type": "locked", "error": null }` and must answer with `unlock`. A wrong code gets
`locked` again with an `error`; after 5 wrong codes the socket is closed. The right code gets
`welcome`, and the client starts a game. A full server (`SPELLFORGE_MAX_SESSIONS`) sends an
`error` and closes the socket.

```jsonc
// Something happened (new game or a completed round)
{
  "type": "state",
  "state": { /* Game.snapshot(): seed, player_id, depth, turn, status, map (with ">" stairs
               once a level is cleared), entities (incl. appearance, can_act), spells,
               items: [{ "kind": "arcane_shard", "pos": [x, y] }] on the floor,
               inventory: { "arcane_shard": 1 } carried by the player */ },
  "events": [ { "type": "damaged", "turn": 3, "target": 4, "pos": [5, 2], "amount": 5, ... } ],
  "log": ["You cast Firebolt.", "The goblin takes 5 damage (1 HP left)."],
  // Pixel art for plugin sprites the client hasn't received yet in this run.
  "sprites": { "goblin": { "palette": { "k": "#140d1c", "g": "#5caa3c" }, "rows": ["..."] } }
}

// Rejected (invalid action, malformed message). Game state is unchanged.
{ "type": "error", "message": "not enough mana for Firebolt" }
```

- `state` is the full snapshot, not a diff. The map is about 1 KB, so simplicity wins.
- The dungeon is endless: `level_cleared` and `level_started` (with `shard: true` on levels
  that hide an arcane shard: depths 1, 4, 7, ...) events mark progress, and the run ends with
  `status: "lost"` when the player dies. Stepping on a shard emits `item_picked_up`.
- An entity's `appearance` is the sprite id to draw (for example `"rock"` while petrified).
  `null` means the client's default art for its kind.
- `events` are structured engine events (see `engine/events.py`). The client uses them
  for effects such as hit flashes and floating damage numbers.
- `log` is the same events rendered as text by `spellforge/narration.py`, shared with
  the terminal client. Clients must display it as text, never as HTML, because
  AI-written plugins can put arbitrary strings in it.

### The forge

```jsonc
// On connect: is the forge usable (API key configured), in which mode, and is the DM on?
{ "type": "welcome", "forge_available": true, "forge_status": "ready",
  "forge_mode": "team" | "single", "dungeon_master": true }

// After "invent" (which needs a carried arcane shard), pushed while the game keeps running.
// "started" spends the shard; `state` shows the new count.
{ "type": "forge", "status": "started", "message": "...", "idea": "...", "mode": "team",
  "state": { /* snapshot */ } }
{ "type": "forge", "status": "working", "message": "The Balancer adjusted the numbers.",
  "stage": "designing" | "balancing" | "coding" | "drawing" | "writing" | "testing"
         | "retrying" | "loading",
  // optional, mostly from the agent team (agents overlap, so steps report when they finish):
  "done": true, "detail": "one or two sentences of the agent's output",
  "verdict": "approve" | "adjust" | "reject",
  "changes": [{ "field": "cooldown", "before": "3", "after": "4", "reason": "..." }] }

// Success: the spell is already in the spellbook; `state` is the updated snapshot.
{ "type": "forge", "status": "done", "message": "...", "spell": { /* spell entry */ },
  "notes": "...", "source": "def on_cast(ctx, caster, target): ...", "warnings": [],
  "attempts": 1, "seconds": 14.7, "input_tokens": 6600, "output_tokens": 1200,
  "cost_usd": 0.05, "team": { "design": {...}, "review": {...}, "speculation": "used",
  "agents": { "coder": { "model": "...", "seconds": 9.6, "tokens": 9000, "cost_usd": 0.02 } } },
  "state": { /* snapshot */ }, "sprites": { /* art the spell introduced */ } }

// Failure (also used when the forge is busy, offline, locked without a shard, over the daily
// budget, or the run has ended). A failed forge run gives the shard back and includes `state`.
{ "type": "forge", "status": "failed", "message": "...", "problems": ["line 3: ..."],
  "state": { /* snapshot, when the shard was returned */ } }
```

A forge `done` or `failed` message is not a reply to `action`, so clients must not treat it
as one (for example, when deciding whether another action may be sent).

### The Dungeon Master

Same shape as the forge, pushed after a level is cleared:

```jsonc
{ "type": "dungeon_master", "status": "started", "message": "...", "depth": 2 }
{ "type": "dungeon_master", "status": "working", "message": "...", "stage": "balancing", "done": true, ... }
{ "type": "dungeon_master", "status": "done", "message": "...",
  "monster": { "id": "...", "name": "Patient Stalker", "description": "...", "counters": "...",
               "weakness": "...", "taunt": "...", "sprite": "dm_3_art", "max_hp": 10,
               "attack": 3, "first_depth": 2 },
  "review": { "verdict": "approve", "rationale": "...", "changes": [] },
  "source": "...", "seconds": 47.0, "cost_usd": 0.06, "sprites": { /* the monster's art */ } }
{ "type": "dungeon_master", "status": "failed", "message": "..." }
```
