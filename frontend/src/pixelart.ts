// Pure helpers for pixel art stored as text grids. No DOM here, so it is unit-tested.

export const SPRITE_SIZE = 16;

export interface PixelArt {
  palette: Record<string, string>; // character -> "#rrggbb"
  rows: string[]; // SPRITE_SIZE rows of SPRITE_SIZE characters; "." is transparent
}

export type Rgb = [r: number, g: number, b: number];

export function parseHex(hex: string): Rgb {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!match) throw new Error(`invalid color ${hex}`);
  return [parseInt(match[1]!, 16), parseInt(match[2]!, 16), parseInt(match[3]!, 16)];
}

/** Problems with a piece of art (wrong size, unknown palette characters), or [] if valid. */
export function validateArt(art: PixelArt): string[] {
  const problems: string[] = [];
  if (art.rows.length !== SPRITE_SIZE) problems.push(`expected ${SPRITE_SIZE} rows`);
  art.rows.forEach((row, y) => {
    if (row.length !== SPRITE_SIZE) problems.push(`row ${y} has ${row.length} pixels`);
    for (const ch of row) {
      if (ch !== "." && !(ch in art.palette)) problems.push(`row ${y}: no color for "${ch}"`);
    }
  });
  for (const [ch, color] of Object.entries(art.palette)) {
    if (!/^#[0-9a-f]{6}$/i.test(color)) problems.push(`bad color for "${ch}": ${color}`);
  }
  return problems;
}

/** Mix `color` toward `toward` by `amount` (0 = unchanged, 1 = fully `toward`). */
export function mix(color: Rgb, toward: Rgb, amount: number): Rgb {
  return color.map((c, i) => Math.round(c + (toward[i]! - c) * amount)) as Rgb;
}

/** RGBA bytes (row-major) for the art, optionally tinted, ready for an ImageData. */
export function toRgba(
  art: PixelArt,
  tint?: { color: Rgb; amount: number },
): Uint8ClampedArray<ArrayBuffer> {
  const bytes = new Uint8ClampedArray(SPRITE_SIZE * SPRITE_SIZE * 4);
  art.rows.forEach((row, y) => {
    [...row].forEach((ch, x) => {
      if (ch === ".") return;
      let rgb = parseHex(art.palette[ch]!);
      if (tint) rgb = mix(rgb, tint.color, tint.amount);
      const i = (y * SPRITE_SIZE + x) * 4;
      bytes.set([...rgb, 255], i);
    });
  });
  return bytes;
}
