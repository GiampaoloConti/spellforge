# Client ↔ server protocol

The browser and the Python server talk over one websocket at `/ws`, using JSON
messages. The server is authoritative: the client sends *intents* and draws whatever
state comes back. Each connection owns its own game.

Sources of truth: [`backend/spellforge/server/protocol.py`](../backend/spellforge/server/protocol.py)
(pydantic models) and [`frontend/src/protocol.ts`](../frontend/src/protocol.ts) (TypeScript
types). Keep them in sync.

## Client → server

```jsonc
{ "type": "new_game", "seed": 42 }          // seed optional (null = random)
{ "type": "action", "action": { "kind": "move", "dx": 1, "dy": -1 } }   // dx, dy in -1..1
{ "type": "action", "action": { "kind": "wait" } }
{ "type": "action", "action": { "kind": "cast", "spell": "firebolt", "target": [12, 5] } }
{ "type": "action", "action": { "kind": "cast", "spell": "frost_nova", "target": null } }
{ "type": "invent", "idea": "chain lightning that jumps between 3 enemies" }   // 3-300 chars
```

Messages are validated strictly: unknown fields, out-of-range values and messages over
4 KB are rejected with an `error` reply before they reach the engine.

## Server → client

`new_game` and `action` get exactly one reply (`state` or `error`). The server also pushes
`welcome` on connect and `forge` updates at any time.

```jsonc
// Something happened (new game or a completed round)
{
  "type": "state",
  "state": { /* Game.snapshot(): seed, player_id, depth, turn, status, map (with ">" stairs
               once a level is cleared), entities (incl. appearance, can_act), spells */ },
  "events": [ { "type": "damaged", "turn": 3, "target": 4, "pos": [5, 2], "amount": 5, ... } ],
  "log": ["You cast Firebolt.", "The goblin takes 5 damage (1 HP left)."],
  // Pixel art for plugin sprites the client hasn't received yet in this run.
  "sprites": { "goblin": { "palette": { "k": "#140d1c", "g": "#5caa3c" }, "rows": ["..."] } }
}

// Rejected (invalid action, malformed message). Game state is unchanged.
{ "type": "error", "message": "not enough mana for Firebolt" }
```

- `state` is the full snapshot, not a diff. The map is about 1 KB, so simplicity wins.
- The dungeon is endless: `level_cleared` and `level_started` events mark progress, and the
  run ends with `status: "lost"` when the player dies.
- An entity's `appearance` is the sprite id to draw (for example `"rock"` while petrified).
  `null` means the client's default art for its kind.
- `events` are structured engine events (see `engine/events.py`). The client uses them
  for effects such as hit flashes and floating damage numbers.
- `log` is the same events rendered as text by `spellforge/narration.py`, shared with
  the terminal client. Clients must display it as text, never as HTML, because
  AI-written plugins can put arbitrary strings in it.

### The forge

```jsonc
// On connect: is the forge usable (API key configured)?
{ "type": "welcome", "forge_available": true, "forge_status": "ready" }

// After "invent", pushed while the game keeps running:
{ "type": "forge", "status": "started", "message": "...", "idea": "..." }
{ "type": "forge", "status": "working", "stage": "writing" | "testing" | "retrying" | "loading",
  "message": "Testing chain_lightning in the sandbox…" }

// Success: the spell is already in the spellbook; `state` is the updated snapshot.
{ "type": "forge", "status": "done", "message": "...", "spell": { /* spell entry */ },
  "notes": "...", "source": "def on_cast(ctx, caster, target): ...", "warnings": [],
  "attempts": 1, "seconds": 14.7, "input_tokens": 6600, "output_tokens": 1200,
  "state": { /* snapshot */ }, "sprites": { /* art the spell introduced */ } }

// Failure (also used when the forge is busy, offline, or the run has ended).
{ "type": "forge", "status": "failed", "message": "...", "problems": ["line 3: ..."] }
```

A forge `done` or `failed` message is not a reply to `action`, so clients must not treat it
as one (for example, when deciding whether another action may be sent).
