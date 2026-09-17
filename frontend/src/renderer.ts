// Draws the game state onto a <canvas>. Knows nothing about the network or input.

import { FLASH_MS, FLOAT_MS, type Effects } from "./effects";
import { entityAt, hasLineOfSight, isWall, line, player, targetProblem } from "./grid";
import type { EntityState, GameState, Point, SpellState } from "./protocol";

export interface Targeting {
  spell: SpellState;
  cursor: Point;
}

const COLORS = {
  void: "#0b0910",
  floor: "#181421",
  floorDot: "#2b2438",
  wall: "#3b3350",
  wallEdge: "#574c73",
  player: "#ffd76a",
  enemy: "#ff6b6b",
  ally: "#6fdc8c",
  frozen: "rgba(124, 199, 255, 0.35)",
  status: "#b48cff",
  inRange: "rgba(180, 140, 255, 0.2)",
  valid: "#b48cff",
  invalid: "#ff5470",
  hpBack: "rgba(0, 0, 0, 0.6)",
  hp: "#6fdc8c",
  hpLow: "#ff5470",
};

const FONT = 'ui-monospace, "Cascadia Mono", Consolas, "Courier New", monospace';

export class Renderer {
  tile = 24;
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    // `!` asserts "this is not null": getContext("2d") only fails on exotic setups.
    this.ctx = canvas.getContext("2d")!;
  }

  /** Fit the map into `container`'s width, keeping tiles square and crisp on HiDPI. */
  resize(state: GameState, container: HTMLElement): void {
    const cols = state.map[0]?.length ?? 1;
    const rows = state.map.length;
    const maxHeight = window.innerHeight * 0.75;
    this.tile = Math.max(12, Math.floor(Math.min(container.clientWidth / cols, maxHeight / rows)));
    const dpr = window.devicePixelRatio || 1;
    this.canvas.style.width = `${cols * this.tile}px`;
    this.canvas.style.height = `${rows * this.tile}px`;
    this.canvas.width = Math.round(cols * this.tile * dpr);
    this.canvas.height = Math.round(rows * this.tile * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /** The map tile under a mouse position, or null outside the canvas. */
  tileAt(state: GameState, clientX: number, clientY: number): Point | null {
    const rect = this.canvas.getBoundingClientRect();
    const x = Math.floor((clientX - rect.left) / this.tile);
    const y = Math.floor((clientY - rect.top) / this.tile);
    const inside = y >= 0 && y < state.map.length && x >= 0 && x < (state.map[0]?.length ?? 0);
    return inside ? [x, y] : null;
  }

  draw(state: GameState, targeting: Targeting | null, effects: Effects, now: number): void {
    const { ctx } = this;
    ctx.fillStyle = COLORS.void;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    this.drawMap(state);
    if (targeting) this.drawTargeting(state, targeting);
    for (const entity of state.entities) this.drawEntity(entity, state);
    this.drawEffects(effects, now);
  }

  private drawMap(state: GameState): void {
    const { ctx, tile } = this;
    state.map.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const px = x * tile;
        const py = y * tile;
        if (row[x] === "#") {
          // Only draw walls that touch a floor, so solid rock stays dark.
          if (!this.touchesFloor(state, x, y)) continue;
          ctx.fillStyle = COLORS.wall;
          ctx.fillRect(px, py, tile, tile);
          ctx.fillStyle = COLORS.wallEdge;
          ctx.fillRect(px, py, tile, Math.max(2, tile / 8));
        } else {
          ctx.fillStyle = COLORS.floor;
          ctx.fillRect(px, py, tile, tile);
          ctx.fillStyle = COLORS.floorDot;
          const dot = Math.max(1, tile / 12);
          ctx.fillRect(px + tile / 2 - dot / 2, py + tile / 2 - dot / 2, dot, dot);
        }
      }
    });
  }

  private touchesFloor(state: GameState, x: number, y: number): boolean {
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const cell = state.map[y + dy]?.[x + dx];
        if (cell !== undefined && cell !== "#") return true;
      }
    }
    return false;
  }

  private drawTargeting(state: GameState, { spell, cursor }: Targeting): void {
    const { ctx, tile } = this;
    const me = player(state);
    if (!me) return;

    // Shade every tile that would be a legal target.
    ctx.fillStyle = COLORS.inRange;
    const r = spell.range;
    for (let y = me.pos[1] - r; y <= me.pos[1] + r; y++) {
      for (let x = me.pos[0] - r; x <= me.pos[0] + r; x++) {
        const reachable =
          !isWall(state, [x, y]) &&
          (!spell.requires_line_of_sight || hasLineOfSight(state, me.pos, [x, y]));
        if (reachable) ctx.fillRect(x * tile, y * tile, tile, tile);
      }
    }

    const problem = targetProblem(state, spell, cursor);
    const color = problem ? COLORS.invalid : COLORS.valid;
    ctx.fillStyle = color;
    for (const [x, y] of line(me.pos, cursor).slice(0, -1)) {
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc((x + 0.5) * tile, (y + 0.5) * tile, tile / 10, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.strokeRect(cursor[0] * tile + 1, cursor[1] * tile + 1, tile - 2, tile - 2);
  }

  private drawEntity(entity: EntityState, state: GameState): void {
    const { ctx, tile } = this;
    const [x, y] = entity.pos;
    const px = x * tile;
    const py = y * tile;

    if (entity.statuses.some((s) => s.id === "frozen")) {
      ctx.fillStyle = COLORS.frozen;
      ctx.fillRect(px + 1, py + 1, tile - 2, tile - 2);
    } else if (entity.statuses.length > 0) {
      ctx.fillStyle = COLORS.status;
      ctx.beginPath();
      ctx.arc(px + tile - tile / 6, py + tile / 6, tile / 10, 0, Math.PI * 2);
      ctx.fill();
    }

    const isPlayer = entity.id === state.player_id;
    ctx.fillStyle = isPlayer
      ? COLORS.player
      : entity.faction === "player"
        ? COLORS.ally
        : COLORS.enemy;
    ctx.font = `bold ${Math.round(tile * 0.78)}px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(entity.glyph, px + tile / 2, py + tile / 2 + 1);

    if (entity.hp < entity.max_hp) {
      const width = tile - 4;
      const height = Math.max(2, Math.round(tile / 10));
      const ratio = Math.max(0, entity.hp / entity.max_hp);
      ctx.fillStyle = COLORS.hpBack;
      ctx.fillRect(px + 2, py + tile - height - 1, width, height);
      ctx.fillStyle = ratio > 0.35 ? COLORS.hp : COLORS.hpLow;
      ctx.fillRect(px + 2, py + tile - height - 1, width * ratio, height);
    }
  }

  private drawEffects(effects: Effects, now: number): void {
    const { ctx, tile } = this;
    for (const flash of effects.flashes) {
      const alpha = 0.55 * (1 - (now - flash.start) / FLASH_MS);
      ctx.fillStyle = `rgba(${flash.color}, ${Math.max(0, alpha)})`;
      ctx.fillRect(flash.pos[0] * tile, flash.pos[1] * tile, tile, tile);
    }
    ctx.font = `bold ${Math.round(tile * 0.6)}px ${FONT}`;
    ctx.textAlign = "center";
    for (const floater of effects.floaters) {
      const t = (now - floater.start) / FLOAT_MS;
      ctx.globalAlpha = Math.max(0, 1 - t * t);
      const fx = (floater.pos[0] + 0.5) * tile;
      const fy = (floater.pos[1] + 0.25) * tile - t * tile * 0.9;
      ctx.lineWidth = 3;
      ctx.strokeStyle = COLORS.void;
      ctx.strokeText(floater.text, fx, fy);
      ctx.fillStyle = floater.color;
      ctx.fillText(floater.text, fx, fy);
    }
    ctx.globalAlpha = 1;
  }
}

/** One-line description of whatever is on a tile, for the hover readout. */
export function describeTile(state: GameState, pos: Point): string {
  const entity = entityAt(state, pos);
  if (!entity) return "";
  const who = entity.id === state.player_id ? "You" : entity.name;
  const statuses = entity.statuses
    .map((s) => (s.remaining === null ? s.id : `${s.id} (${s.remaining})`))
    .join(", ");
  return `${who}: HP ${entity.hp}/${entity.max_hp}, attack ${entity.attack}${statuses ? `, ${statuses}` : ""}`;
}
