// Turns pixel art into small canvases once, then hands out the cached images.

import { CREATURES, TILES } from "./art";
import { SPRITE_SIZE, toRgba, type PixelArt } from "./pixelart";

const FROZEN_TINT = { color: [150, 225, 255] as [number, number, number], amount: 0.55 };

const cache = new Map<string, HTMLCanvasElement>();

function render(key: string, art: PixelArt, frozen = false): HTMLCanvasElement {
  const cached = cache.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SPRITE_SIZE;
  const pixels = toRgba(art, frozen ? FROZEN_TINT : undefined);
  canvas.getContext("2d")!.putImageData(new ImageData(pixels, SPRITE_SIZE, SPRITE_SIZE), 0, 0);
  cache.set(key, canvas);
  return canvas;
}

/** The sprite for a creature kind, or null if there is no art for it (draw a glyph instead). */
export function creatureSprite(kind: string, frozen: boolean): HTMLCanvasElement | null {
  const art = CREATURES[kind];
  return art ? render(`creature:${kind}:${frozen}`, art, frozen) : null;
}

export function floorSprite(variant: number): HTMLCanvasElement {
  const index = variant % TILES.floor.length;
  return render(`floor:${index}`, TILES.floor[index]!);
}

export function wallSprite(kind: "wall_face" | "wall_top"): HTMLCanvasElement {
  return render(kind, TILES[kind]);
}
