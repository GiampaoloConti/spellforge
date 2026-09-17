import { describe, expect, it } from "vitest";
import { CREATURES, TILES } from "./art";
import { mix, parseHex, toRgba, validateArt, type PixelArt } from "./pixelart";

describe("pixel art", () => {
  const all: [string, PixelArt][] = [
    ...Object.entries(CREATURES),
    ...TILES.floor.map((art, i): [string, PixelArt] => [`floor ${i}`, art]),
    ["wall_face", TILES.wall_face],
    ["wall_top", TILES.wall_top],
    ["stairs", TILES.stairs],
  ];

  it.each(all)("%s is a valid 16x16 grid with a complete palette", (_name, art) => {
    expect(validateArt(art)).toEqual([]);
  });

  it("reports malformed art", () => {
    const bad: PixelArt = { palette: { a: "red" }, rows: ["ab"] };
    expect(validateArt(bad)).toEqual(
      expect.arrayContaining(['row 0: no color for "b"', "expected 16 rows", 'bad color for "a": red']),
    );
  });

  it("converts to RGBA with transparency and optional tint", () => {
    const art: PixelArt = { palette: { x: "#ff0000" }, rows: ["x" + ".".repeat(15), ...Array(15).fill(".".repeat(16))] };
    const plain = toRgba(art);
    expect([...plain.slice(0, 8)]).toEqual([255, 0, 0, 255, 0, 0, 0, 0]);
    const tinted = toRgba(art, { color: [0, 0, 255], amount: 0.5 });
    expect([...tinted.slice(0, 4)]).toEqual([128, 0, 128, 255]);
  });

  it("parses and mixes colors", () => {
    expect(parseHex("#0a1B2c")).toEqual([10, 27, 44]);
    expect(mix([0, 100, 200], [100, 100, 100], 0.5)).toEqual([50, 100, 150]);
  });
});
