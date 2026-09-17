// Message shapes exchanged with the server over the websocket.
// Mirrors backend/spellforge/server/protocol.py and Game.snapshot(). Keep them in sync.
//
// TS notes: `interface` and `type` both describe the shape of plain objects; nothing here
// exists at runtime. `"a" | "b"` is a union of literal strings, and a union of object
// types that share a `type`/`kind` field is a "discriminated union": after checking
// `msg.type === "state"`, TypeScript knows exactly which fields `msg` has.

export type Point = [x: number, y: number];

export type Faction = "player" | "enemy";

export interface StatusState {
  id: string;
  remaining: number | null; // null = permanent
}

export interface EntityState {
  id: number;
  kind: string;
  name: string;
  glyph: string;
  faction: Faction;
  pos: Point;
  hp: number;
  max_hp: number;
  mana: number;
  max_mana: number;
  attack: number;
  statuses: StatusState[];
}

export type SpellTarget = "self" | "tile" | "entity";

export interface SpellState {
  id: string;
  name: string;
  description: string;
  mana_cost: number;
  target: SpellTarget;
  range: number;
  requires_line_of_sight: boolean;
  cooldown_remaining: number;
  disabled: boolean;
}

export interface GameState {
  seed: number;
  player_id: number;
  turn: number;
  status: "playing" | "won" | "lost";
  map: string[]; // rows of "#" (wall) and "." (floor)
  entities: EntityState[];
  spells: SpellState[];
  disabled_plugins: Record<string, string>;
}

// Engine events. Only the fields the client uses are typed; see engine/events.py.
export interface GameEvent {
  type: string;
  turn: number;
  pos?: Point;
  amount?: number;
  [field: string]: unknown;
}

export type ServerMessage =
  | { type: "state"; state: GameState; events: GameEvent[]; log: string[] }
  | { type: "error"; message: string };

export type ActionPayload =
  | { kind: "move"; dx: number; dy: number }
  | { kind: "wait" }
  | { kind: "cast"; spell: string; target: Point | null };

export type ClientMessage =
  | { type: "new_game"; seed: number | null }
  | { type: "action"; action: ActionPayload };
