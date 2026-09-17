// Turns pixel art into small canvases once, then hands out the cached images.
//
// Two sources of creature art: the player's sprite in art.ts, and sprites defined by
// plugins on the server (monsters, forged spells), registered as they arrive.

import { CREATURES, TILES } from "./art";
import { SPRITE_SIZE, toRgba, validateArt, type PixelArt } from "./pixelart";
import type { SpriteArt } from "./protocol";

const FROZEN_TINT = { color: [150, 225, 255] as [number, number, number], amount: 0.55 };

const cache = new Map<string, HTMLCanvasElement>();
const pluginArt = new Map<string, PixelArt>();

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

function forgetPluginSprite(id: string): void {
  pluginArt.delete(id);
  cache.delete(`plugin:${id}:false`);
  cache.delete(`plugin:${id}:true`);
}

/** Add art from the server. Malformed art is ignored (the glyph is drawn instead). */
export function registerSprites(sprites: Record<string, SpriteArt>): void {
  for (const [id, art] of Object.entries(sprites)) {
    forgetPluginSprite(id);
    if (validateArt(art).length === 0) pluginArt.set(id, art);
  }
}

/** A new run gets its own plugins, so forget everything they defined. */
export function clearPluginSprites(): void {
  for (const id of [...pluginArt.keys()]) forgetPluginSprite(id);
}

/** The image for a sprite id, or null if there is no art for it (draw a glyph instead). */
export function creatureSprite(id: string, frozen: boolean): HTMLCanvasElement | null {
  const fromPlugin = pluginArt.get(id);
  if (fromPlugin) return render(`plugin:${id}:${frozen}`, fromPlugin, frozen);
  const builtin = CREATURES[id];
  return builtin ? render(`creature:${id}:${frozen}`, builtin, frozen) : null;
}

export function floorSprite(variant: number): HTMLCanvasElement {
  const index = variant % TILES.floor.length;
  return render(`floor:${index}`, TILES.floor[index]!);
}

export function tileSprite(kind: "wall_face" | "wall_top" | "stairs"): HTMLCanvasElement {
  return render(kind, TILES[kind]);
}
