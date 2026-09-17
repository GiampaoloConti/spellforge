// Draws the game state onto a <canvas> with pixel-art sprites and a camera that follows
// the player. Knows nothing about the network or input.

import { creatureSprite, floorSprite, tileSprite } from "./atlas";
import { FLASH_MS, FLOAT_MS, type Effects } from "./effects";
import {
  cameraOrigin,
  entityAt,
  hasLineOfSight,
  isWall,
  line,
  player,
  targetProblem,
  tileHash,
  tileKind,
} from "./grid";
import { SPRITE_SIZE } from "./pixelart";
import type { EntityState, GameState, Point, SpellState } from "./protocol";

export interface Targeting {
  spell: SpellState;
  cursor: Point;
}

const COLORS = {
  void: "#0b0910",
  enemyGlyph: "#ff6b6b",
  allyGlyph: "#6fdc8c",
  shadow: "rgba(0, 0, 0, 0.35)",
  allyRing: "rgba(111, 220, 140, 0.8)",
  inRange: "rgba(180, 140, 255, 0.16)",
  valid: "#b48cff",
  invalid: "#ff5470",
  hpBack: "rgba(0, 0, 0, 0.7)",
  hp: "#6fdc8c",
  hpLow: "#ff5470",
};

const FONT = 'ui-monospace, "Cascadia Mono", Consolas, "Courier New", monospace';
/** Creatures bob on this beat, so the board is redrawn at least this often. */
export const BOB_MS = 420;

export class Renderer {
  /** On-screen size of one map tile in CSS pixels: always a whole multiple of 16. */
  tile = SPRITE_SIZE * 2;
  private scale = 2;
  private view = { cols: 1, rows: 1 };
  private camera = { x: 0, y: 0 };
  private readonly facing = new Map<number, 1 | -1>();
  private readonly lastX = new Map<number, number>();
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    // `!` asserts "this is not null": getContext("2d") only fails on exotic setups.
    this.ctx = canvas.getContext("2d")!;
  }

  /**
   * Pick a whole-number zoom so pixel art stays crisp. If the whole map fits at 2x or more,
   * show it all; otherwise zoom to 2x and let the camera follow the player.
   */
  resize(state: GameState, container: HTMLElement): void {
    const cols = state.map[0]?.length ?? 1;
    const rows = state.map.length;
    const width = container.clientWidth;
    const height = window.innerHeight * 0.72;
    const fitScale = Math.floor(Math.min(width / (cols * SPRITE_SIZE), height / (rows * SPRITE_SIZE)));
    this.scale = fitScale >= 2 ? fitScale : width < SPRITE_SIZE * 2 * 12 ? 1 : 2;
    this.tile = SPRITE_SIZE * this.scale;
    this.view = {
      cols: Math.min(cols, Math.floor(width / this.tile)),
      rows: Math.min(rows, Math.floor(height / this.tile)),
    };

    const dpr = window.devicePixelRatio || 1;
    this.canvas.style.width = `${this.view.cols * this.tile}px`;
    this.canvas.style.height = `${this.view.rows * this.tile}px`;
    this.canvas.width = Math.round(this.view.cols * this.tile * dpr);
    this.canvas.height = Math.round(this.view.rows * this.tile * dpr);
  }

  /** Forget per-creature animation state (entity ids restart in a new game). */
  reset(): void {
    this.facing.clear();
    this.lastX.clear();
  }

  /** The map tile under a mouse position, or null outside the visible map. */
  tileAt(state: GameState, clientX: number, clientY: number): Point | null {
    const rect = this.canvas.getBoundingClientRect();
    const x = Math.floor((clientX - rect.left) / this.tile) + this.camera.x;
    const y = Math.floor((clientY - rect.top) / this.tile) + this.camera.y;
    const inside = y >= 0 && y < state.map.length && x >= 0 && x < (state.map[0]?.length ?? 0);
    return inside ? [x, y] : null;
  }

  draw(state: GameState, targeting: Targeting | null, effects: Effects, now: number): void {
    const { ctx } = this;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false; // nearest-neighbour scaling keeps pixels sharp
    ctx.fillStyle = COLORS.void;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    const me = player(state);
    if (me) {
      this.camera = {
        x: cameraOrigin(me.pos[0], this.view.cols, state.map[0]?.length ?? 1),
        y: cameraOrigin(me.pos[1], this.view.rows, state.map.length),
      };
    }
    // From here on, draw in map coordinates: the translation scrolls the camera.
    ctx.translate(-this.camera.x * this.tile, -this.camera.y * this.tile);

    this.drawMap(state);
    if (targeting) this.drawTargeting(state, targeting);
    this.updateFacing(state);
    const byRow = [...state.entities].sort((a, b) => a.pos[1] - b.pos[1] || a.id - b.id);
    for (const entity of byRow) this.drawEntity(entity, state, now);
    this.drawEffects(effects, now);
  }

  private drawMap(state: GameState): void {
    const { ctx, tile } = this;
    const x0 = this.camera.x;
    const y0 = this.camera.y;
    for (let y = y0; y < Math.min(state.map.length, y0 + this.view.rows + 1); y++) {
      for (let x = x0; x < Math.min(state.map[y]!.length, x0 + this.view.cols + 1); x++) {
        const kind = tileKind(state, x, y);
        if (kind === "void") continue;
        const sprite = kind === "floor" ? floorSprite(tileHash(x, y)) : tileSprite(kind);
        ctx.drawImage(sprite, x * tile, y * tile, tile, tile);
      }
    }
  }

  private drawTargeting(state: GameState, { spell, cursor }: Targeting): void {
    const { ctx, tile } = this;
    const me = player(state);
    if (!me) return;

    // Shade every tile the spell could reach.
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
    ctx.globalAlpha = 0.6;
    for (const [x, y] of line(me.pos, cursor).slice(0, -1)) {
      ctx.fillRect((x + 0.5) * tile - this.scale * 1.5, (y + 0.5) * tile - this.scale * 1.5, this.scale * 3, this.scale * 3);
    }
    ctx.globalAlpha = 1;
    this.drawReticle(cursor, color);
  }

  /** Pixel-art corner brackets around a tile. */
  private drawReticle([x, y]: Point, color: string): void {
    const { ctx, tile, scale } = this;
    const px = x * tile;
    const py = y * tile;
    const arm = 5 * scale;
    const w = 2 * scale;
    ctx.fillStyle = color;
    for (const [cx, cy, sx, sy] of [
      [px, py, 1, 1],
      [px + tile, py, -1, 1],
      [px, py + tile, 1, -1],
      [px + tile, py + tile, -1, -1],
    ] as const) {
      ctx.fillRect(sx > 0 ? cx : cx - arm, sy > 0 ? cy : cy - w, arm, w);
      ctx.fillRect(sx > 0 ? cx : cx - w, sy > 0 ? cy : cy - arm, w, arm);
    }
  }

  /** Creatures face the way they last moved; idle monsters turn toward the player. */
  private updateFacing(state: GameState): void {
    const me = player(state);
    for (const entity of state.entities) {
      const previousX = this.lastX.get(entity.id);
      const dx = previousX === undefined ? 0 : entity.pos[0] - previousX;
      if (dx !== 0) {
        this.facing.set(entity.id, dx > 0 ? 1 : -1);
      } else if (entity.id !== state.player_id && me && me.pos[0] !== entity.pos[0]) {
        this.facing.set(entity.id, me.pos[0] > entity.pos[0] ? 1 : -1);
      }
      this.lastX.set(entity.id, entity.pos[0]);
    }
  }

  private drawEntity(entity: EntityState, state: GameState, now: number): void {
    const { ctx, tile, scale } = this;
    const [x, y] = entity.pos;
    const px = x * tile;
    const py = y * tile;
    const frozen = entity.statuses.some((s) => s.id === "frozen");
    const isAlly = entity.faction === "player" && entity.id !== state.player_id;

    // Ground shadow (and a ring for allies).
    ctx.fillStyle = COLORS.shadow;
    ctx.beginPath();
    ctx.ellipse(px + tile / 2, py + tile - 1.5 * scale, tile * 0.32, 2.5 * scale, 0, 0, Math.PI * 2);
    ctx.fill();
    if (isAlly) {
      ctx.strokeStyle = COLORS.allyRing;
      ctx.lineWidth = scale;
      ctx.stroke();
    }

    // Idle bob: every other beat, shifted by id so creatures don't move in lockstep.
    const beat = Math.floor(now / BOB_MS) + entity.id;
    const bob = entity.can_act && beat % 2 === 1 ? -scale : 0;

    const sprite = creatureSprite(entity.appearance ?? entity.kind, frozen);
    if (sprite) {
      const flip = this.facing.get(entity.id) === -1;
      ctx.save();
      ctx.translate(flip ? px + tile : px, py + bob);
      ctx.scale(flip ? -1 : 1, 1);
      ctx.drawImage(sprite, 0, 0, tile, tile);
      ctx.restore();
    } else {
      // No art for this kind (e.g. a freshly generated monster): fall back to its glyph.
      ctx.fillStyle = isAlly ? COLORS.allyGlyph : COLORS.enemyGlyph;
      ctx.font = `bold ${Math.round(tile * 0.75)}px ${FONT}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(entity.glyph, px + tile / 2, py + tile / 2 + bob);
    }

    if (entity.hp < entity.max_hp) {
      const width = tile - 6 * scale;
      const height = 2 * scale;
      const ratio = Math.max(0, entity.hp / entity.max_hp);
      const bx = px + 3 * scale;
      const by = py - scale;
      ctx.fillStyle = COLORS.hpBack;
      ctx.fillRect(bx - scale / 2, by - scale / 2, width + scale, height + scale);
      ctx.fillStyle = ratio > 0.35 ? COLORS.hp : COLORS.hpLow;
      ctx.fillRect(bx, by, Math.round(width * ratio), height);
    }
  }

  private drawEffects(effects: Effects, now: number): void {
    const { ctx, tile } = this;
    for (const flash of effects.flashes) {
      const alpha = 0.5 * (1 - (now - flash.start) / FLASH_MS);
      ctx.fillStyle = `rgba(${flash.color}, ${Math.max(0, alpha)})`;
      ctx.fillRect(flash.pos[0] * tile, flash.pos[1] * tile, tile, tile);
    }
    ctx.font = `bold ${Math.round(tile * 0.5)}px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const floater of effects.floaters) {
      const t = Math.max(0, (now - floater.start) / FLOAT_MS);
      ctx.globalAlpha = Math.max(0, 1 - t * t);
      const fx = (floater.pos[0] + 0.5) * tile;
      const fy = (floater.pos[1] + 0.3) * tile - t * tile * 0.8;
      ctx.lineWidth = 4;
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
