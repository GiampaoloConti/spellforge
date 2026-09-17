// Pixel art for creatures and tiles, as 16x16 grids of palette characters.
// "." is transparent. Only the player and the tiles live here: monster sprites (and art
// for forged spells) are defined by plugins on the server and arrive with the game state.
// Draft previews were made with a small painter script; edit the grids directly.

import type { PixelArt } from "./pixelart";

export const CREATURES: Record<string, PixelArt> = {
  player: {
    palette: {
      "k": "#140d1c", // outline
      "p": "#5b3a9e", // hat
      "P": "#8a63d2", // hat light
      "q": "#3f2873", // hat shade
      "y": "#f2c14e", // gold
      "s": "#f1c7a1", // skin
      "S": "#c98d6a", // skin shade
      "w": "#eeeaf6", // beard
      "W": "#a9a2bd", // beard shade
      "b": "#2f4f9e", // robe
      "B": "#4f78d0", // robe light
      "d": "#223a78", // robe shade
      "n": "#8b5a2b", // wood
      "c": "#6fe8ff", // orb
      "C": "#e6ffff", // orb glint
    },
    rows: [
      "......kpk....k..",
      ".....kPpk...kck.",
      "....kPpppk.kCcck",
      "....kPppqk.kccck",
      "..kkyyyyyykkknk.",
      ".kPPppppppqqknk.",
      "..kkSSSSSSkkknk.",
      "...kskssksk.knk.",
      "..kBwwwwwWdkknk.",
      "..kBbwwwWbdbsnk.",
      "..kBbbwWbbdkknk.",
      ".kByyyywyyydknk.",
      ".kBbbbbbbbbdknk.",
      ".kBbbbbbbbbdknk.",
      ".kBbbbbbbbbdknk.",
      "..kdddkkdddkknk.",
    ],
  },
};

function tile(rows: string[]): PixelArt {
  return { palette: TILE_PALETTE, rows };
}

const TILE_PALETTE: Record<string, string> = {
  "0": "#241d2e", // floor
  "1": "#2c2438", // floor edge
  "2": "#1d1726", // floor seam
  "3": "#342b42", // floor speck
  "4": "#15101d", // mortar
  "5": "#3a3250", // brick
  "6": "#4a4065", // brick light
  "7": "#2e2740", // brick shade
  "8": "#2c2540", // wall top
  "9": "#3d3456", // wall top light
  "a": "#231d33", // wall top shade
  "b": "#0b0910", // stairwell dark
  "c": "#6a5f8a", // step light
  "d": "#4a4065", // step
  "e": "#2e2740", // step shade
  "f": "#3a3250", // step mid
};

export const TILES = {
  floor: [
    tile([
      "1111111211111112",
      "1000000210000002",
      "1000300210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210002002",
      "2222222222222222",
      "1111111211111112",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210002002",
      "1000000210000002",
      "2222222222222222",
    ]), 
    tile([
      "1111111211111112",
      "1000000210000002",
      "1200000210000002",
      "1000000210000002",
      "1000000210000002",
      "1300000210030002",
      "1000000210000002",
      "2222222222222222",
      "1111111211111112",
      "1000000210000002",
      "1000000210000002",
      "1000000210003002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "2222222222222222",
    ]), 
    tile([
      "1111111211111112",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "2222222222222222",
      "1111111211111112",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "1000000210000002",
      "2222222222222222",
    ]),
  ],
  wall_face: tile([
    "9999999999999999",
    "8888888888888888",
    "8888888888888888",
    "8888888888888888",
    "4444444444444444",
    "6666666466666664",
    "5555555455555554",
    "7777777477777774",
    "4444444444444444",
    "6664666666646666",
    "5554555555545555",
    "7774777777747777",
    "4444444444444444",
    "6666666466666664",
    "5555555455555554",
    "7777777477777774",
  ]),
  wall_top: tile([
    "8a8a889898aa88a8",
    "88888988aa888888",
    "8a98888888888888",
    "888a88a898888888",
    "888888a888888898",
    "8a98a888a8888888",
    "888a888888988888",
    "8889888888a8aa88",
    "899aa8988a888a88",
    "88aa8888988a8988",
    "8888888888888888",
    "8889988888888888",
    "88888888a8888888",
    "88888888aa88a888",
    "88a9888888888888",
    "88a8888888888988",
  ]),
  stairs: tile([
    "1111111111111111",
    "1000000000000002",
    "10eeeeeeeeeeee02",
    "10eccccccccccc02",
    "10eddddddddddd02",
    "10ebbbbbbbbbbb02",
    "10ebbddddddddd02",
    "10ebbfffffffff02",
    "10ebbbbbbbbbbb02",
    "10ebbbbfffffff02",
    "10ebbbbeeeeeee02",
    "10ebbbbbbbbbbb02",
    "10ebbbbbbeeeee02",
    "10ebbbbbbbbbbb02",
    "1000000000000002",
    "1222222222222222",
  ]),
};

/** Items lying on the floor, by item kind. */
export const ITEMS: Record<string, PixelArt> = {
  arcane_shard: {
    palette: {
      "k": "#140d1c", // outline
      "C": "#f4ffff", // glint
      "c": "#8fe3ff", // crystal
      "v": "#7b5cff", // crystal shade
      "y": "#f2c14e", // sparkle
    },
    rows: [
      "................",
      "................",
      "................",
      "........kk....y.",
      ".......kCck.....",
      "......kCcck.....",
      "......kCcvk.....",
      ".....kCccvk.....",
      ".....kCcvvk.....",
      "....kCccvvk.....",
      "....kCcvvk......",
      "..y.kCcvvk......",
      "...kCcvvk.......",
      "...kccvk........",
      "....kvk.........",
      "................",
    ],
  },
};

/** The Spellforge mark: an anvil with an arcane spark. Also used as the favicon. */
export const SIGIL: PixelArt = {
  palette: {
    "k": "#140d1c", // outline
    "A": "#a7a3b8", // iron light
    "a": "#76728a", // iron
    "d": "#4a4660", // iron shade
    "f": "#8a63d2", // spark
    "F": "#d9c6ff", // spark light
    "y": "#f2c14e", // embers
  },
  rows: [
    "........y.......",
    ".......kfk......",
    "......kfFfk..y..",
    "......kfFFk.....",
    "..y...kFFfk.....",
    ".......kfk......",
    "................",
    "kkkkkkkkkkkkkkkk",
    "kAAAAAAAAAAAAAAk",
    ".kkkaaaaaaaaadk.",
    "....kkaaaaaddk..",
    ".....kaaaaadk...",
    ".....kaaaaadk...",
    "....kaaaaaaadk..",
    "...kAAAAAAAAAdk.",
    "...kkkkkkkkkkkk.",
  ],
};
