// Grid helpers used to preview targeting (range, line of sight) before sending a cast.
// The server re-checks everything; these are only hints. The line algorithm matches
// engine/geometry.py exactly so the hints agree with the server.

import type { EntityState, GameState, Point, SpellState } from "./protocol";

export function distance(a: Point, b: Point): number {
  return Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));
}

export function isWall(state: GameState, [x, y]: Point): boolean {
  const row = state.map[y];
  return row === undefined || x < 0 || x >= row.length || row[x] === "#";
}

/** Tiles on a Bresenham line from `start` (excluded) to `end` (included). */
export function line(start: Point, end: Point): Point[] {
  const points: Point[] = [];
  let [x, y] = start;
  const dx = Math.abs(end[0] - x);
  const dy = -Math.abs(end[1] - y);
  const sx = Math.sign(end[0] - x);
  const sy = Math.sign(end[1] - y);
  let err = dx + dy;
  while (x !== end[0] || y !== end[1]) {
    const e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y += sy;
    }
    points.push([x, y]);
  }
  return points;
}

export function hasLineOfSight(state: GameState, start: Point, end: Point): boolean {
  return !line(start, end)
    .slice(0, -1)
    .some((p) => isWall(state, p));
}

export function entityAt(state: GameState, [x, y]: Point): EntityState | undefined {
  return state.entities.find((e) => e.pos[0] === x && e.pos[1] === y);
}

export function player(state: GameState): EntityState | undefined {
  return state.entities.find((e) => e.id === state.player_id);
}

/** Why the server would reject casting `spell` at `target`, or null if it looks valid. */
export function targetProblem(state: GameState, spell: SpellState, target: Point): string | null {
  const me = player(state);
  if (!me) return "you are dead";
  if (isWall(state, target)) return "invalid target tile";
  if (distance(me.pos, target) > spell.range) return "out of range";
  if (spell.requires_line_of_sight && !hasLineOfSight(state, me.pos, target)) {
    return "no line of sight";
  }
  if (spell.target === "entity" && !entityAt(state, target)) return "no creature there";
  return null;
}

/** Hostile creatures the spell could hit right now, nearest first. */
export function validTargets(state: GameState, spell: SpellState): EntityState[] {
  const me = player(state);
  if (!me) return [];
  return state.entities
    .filter((e) => e.faction !== me.faction && targetProblem(state, spell, e.pos) === null)
    .sort((a, b) => distance(me.pos, a.pos) - distance(me.pos, b.pos) || a.id - b.id);
}

export type TileKind = "floor" | "wall_face" | "wall_top" | "void";

/**
 * How to draw a map cell: walls with floor directly below show their brick face,
 * other walls next to floor show their top, and solid rock is left dark.
 */
export function tileKind(state: GameState, x: number, y: number): TileKind {
  if (!isWall(state, [x, y])) return "floor";
  if (y + 1 < state.map.length && !isWall(state, [x, y + 1])) return "wall_face";
  for (let dy = -1; dy <= 1; dy++) {
    for (let dx = -1; dx <= 1; dx++) {
      const cell = state.map[y + dy]?.[x + dx];
      if (cell !== undefined && cell !== "#") return "wall_top";
    }
  }
  return "void";
}

/** Stable pseudo-random number for a tile, so floor variations don't flicker. */
export function tileHash(x: number, y: number): number {
  let h = Math.imul(x, 374761393) + Math.imul(y, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return (h ^ (h >>> 16)) >>> 0;
}

/** Top-left tile of a `view`-sized window centred on `center`, kept inside the map. */
export function cameraOrigin(center: number, view: number, mapSize: number): number {
  return Math.max(0, Math.min(center - Math.floor(view / 2), mapSize - view));
}
