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
```

Messages are validated strictly: unknown fields, out-of-range values and messages over
4 KB are rejected with an `error` reply before they reach the engine.

## Server → client

Every message gets exactly one reply.

```jsonc
// Something happened (new game or a completed round)
{
  "type": "state",
  "state": { /* Game.snapshot(): seed, player_id, turn, status, map, entities, spells */ },
  "events": [ { "type": "damaged", "turn": 3, "target": 4, "pos": [5, 2], "amount": 5, ... } ],
  "log": ["You cast Firebolt.", "The goblin takes 5 damage (1 HP left)."]
}

// Rejected (invalid action, malformed message). Game state is unchanged.
{ "type": "error", "message": "not enough mana for Firebolt" }
```

- `state` is the full snapshot, not a diff. The map is about 1 KB, so simplicity wins.
- `events` are structured engine events (see `engine/events.py`). The client uses them
  for effects such as hit flashes and floating damage numbers.
- `log` is the same events rendered as text by `spellforge/narration.py`, shared with
  the terminal client. Clients must display it as text, never as HTML, because plugins
  (soon AI-written) can put arbitrary strings in it.

## Planned (M3)

The agent pipeline runs *between* turns, so the server will also push unsolicited
messages, for example `{"type": "forge_progress", ...}` while a spell is being
written, and a `state` message when it is hot-loaded. The one-reply-per-message rule
above will then hold only for `new_game` and `action`.
