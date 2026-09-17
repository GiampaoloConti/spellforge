// A small overview map in the board corner: walls, floor, the stairs (gold) and the
// player (purple). Reads everything from the game state the server already sends.

import { player } from "./grid";
import type { GameState } from "./protocol";

const SCALE = 3; // pixels per tile in the minimap's own resolution (CSS scales it down)
const WALL = "#2e2640";
const FLOOR = "#141019";
const STAIRS = "#f2c14e";
const PLAYER = "#c8a2ff";

export class Minimap {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d")!;
  }

  draw(state: GameState): void {
    const rows = state.map;
    const height = rows.length;
    const width = rows[0]?.length ?? 0;
    if (!width || !height) return;

    if (this.canvas.width !== width * SCALE || this.canvas.height !== height * SCALE) {
      this.canvas.width = width * SCALE;
      this.canvas.height = height * SCALE;
    }
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    for (let y = 0; y < height; y++) {
      const row = rows[y]!;
      for (let x = 0; x < width; x++) {
        const ch = row[x];
        ctx.fillStyle = ch === "#" ? WALL : ch === ">" ? STAIRS : FLOOR;
        ctx.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
      }
    }
    // Make the stairs pointer pop with a ring; it only exists once a level is cleared.
    const stairs = findStairs(rows);
    if (stairs) marker(ctx, stairs[0], stairs[1], STAIRS);
    const me = player(state);
    if (me) marker(ctx, me.pos[0], me.pos[1], PLAYER);
  }
}

function findStairs(rows: string[]): [number, number] | null {
  for (let y = 0; y < rows.length; y++) {
    const x = rows[y]!.indexOf(">");
    if (x !== -1) return [x, y];
  }
  return null;
}

/** A 3x3 dot centred on the tile, so the player and stairs stand out from the terrain. */
function marker(ctx: CanvasRenderingContext2D, tx: number, ty: number, color: string): void {
  ctx.fillStyle = color;
  ctx.fillRect(tx * SCALE - 1, ty * SCALE - 1, SCALE + 2, SCALE + 2);
}
