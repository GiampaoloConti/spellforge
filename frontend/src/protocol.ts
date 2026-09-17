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
  appearance: string | null; // sprite id to draw it with; null = default art for its kind
  can_act: boolean; // false while stunned, frozen, petrified...
  statuses: StatusState[];
}

// 16x16 pixel art sent by the server for plugin-defined sprites (see pixelart.ts).
export interface SpriteArt {
  palette: Record<string, string>;
  rows: string[];
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
  depth: number; // dungeon level, starting at 1
  turn: number;
  status: "playing" | "lost";
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

// Pipeline stages. The agent team uses designing/balancing/coding/drawing/testing, the single
// writer uses writing/testing, and the server adds loading when it hot-loads the result.
export type Stage =
  | "designing"
  | "balancing"
  | "coding"
  | "drawing"
  | "writing"
  | "testing"
  | "retrying"
  | "loading";

export type Verdict = "approve" | "adjust" | "reject";

export interface BalanceChange {
  field: string;
  before: string;
  after: string;
  reason: string;
}

// Optional structured extras on progress messages.
export interface StageDetails {
  stage: Stage;
  done?: boolean; // the step finished
  detail?: string; // the agent's output in one or two sentences
  verdict?: Verdict; // the Balancer's decision
  changes?: BalanceChange[];
}

export interface AgentCost {
  model: string;
  seconds: number;
  tokens: number;
  cost_usd: number;
}

// What the agent team did, for display.
export interface TeamReport {
  design: { name: string; description: string; effects: string[] } | null;
  review: { verdict: Verdict; rationale: string; changes: BalanceChange[] } | null;
  speculation: "off" | "started" | "used" | "discarded" | "failed";
  agents: Record<string, AgentCost>;
}

export interface ForgeDone {
  type: "forge";
  status: "done";
  message: string;
  spell: SpellState;
  notes: string;
  source: string; // the generated plugin code
  warnings: string[];
  attempts: number;
  seconds: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  team: TeamReport | null; // null for the single-agent forge
  state: GameState;
  sprites: Record<string, SpriteArt>; // art the spell introduced, if any
}

export interface CounterMonster {
  id: string;
  name: string;
  description: string;
  counters: string; // which habit of yours it punishes
  weakness: string;
  taunt: string;
  sprite: string | null;
  max_hp: number;
  attack: number;
  first_depth: number;
}

export interface DungeonMasterDone {
  type: "dungeon_master";
  status: "done";
  message: string;
  monster: CounterMonster;
  review: { verdict: Verdict; rationale: string; changes: BalanceChange[] } | null;
  source: string;
  seconds: number;
  cost_usd: number;
  sprites: Record<string, SpriteArt>;
}

export type ServerMessage =
  | {
      type: "state";
      state: GameState;
      events: GameEvent[];
      log: string[];
      sprites: Record<string, SpriteArt>; // only sprites not sent before
    }
  | { type: "error"; message: string }
  | {
      type: "welcome";
      forge_available: boolean;
      forge_status: string;
      forge_mode: "team" | "single" | null;
      dungeon_master: boolean;
    }
  // The forge messages all have type "forge"; `status` tells them apart.
  | { type: "forge"; status: "started"; message: string; idea: string; mode: "team" | "single" }
  | ({ type: "forge"; status: "working"; message: string } & StageDetails)
  | ForgeDone
  | {
      type: "forge";
      status: "failed";
      message: string;
      problems?: string[];
      team?: TeamReport | null;
    }
  // Same pattern for the Dungeon Master.
  | { type: "dungeon_master"; status: "started"; message: string; depth: number }
  | ({ type: "dungeon_master"; status: "working"; message: string } & StageDetails)
  | DungeonMasterDone
  | { type: "dungeon_master"; status: "failed"; message: string };

export type ActionPayload =
  | { kind: "move"; dx: number; dy: number }
  | { kind: "wait" }
  | { kind: "cast"; spell: string; target: Point | null };

export type ClientMessage =
  | { type: "new_game"; seed: number | null }
  | { type: "action"; action: ActionPayload }
  | { type: "invent"; idea: string } // 3-300 characters
  | { type: "dev"; command: "clear_level" | "descend" }; // honoured only with dev tools enabled
