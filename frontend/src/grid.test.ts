import { describe, expect, it } from "vitest";
import {
  cameraOrigin,
  distance,
  hasLineOfSight,
  line,
  targetProblem,
  tileKind,
  validTargets,
} from "./grid";
import type { EntityState, GameState, SpellState } from "./protocol";

function entity(id: number, pos: [number, number], faction: "player" | "enemy"): EntityState {
  return {
    id,
    kind: faction === "player" ? "player" : "goblin",
    name: "x",
    glyph: "g",
    faction,
    pos,
    hp: 5,
    max_hp: 5,
    mana: 0,
    max_mana: 0,
    attack: 1,
    appearance: null,
    can_act: true,
    statuses: [],
  };
}

function game(map: string[], entities: EntityState[]): GameState {
  return {
    seed: 0,
    player_id: 1,
    depth: 1,
    turn: 1,
    status: "playing",
    map,
    entities,
    spells: [],
    disabled_plugins: {},
  };
}

const firebolt: SpellState = {
  id: "firebolt",
  name: "Firebolt",
  description: "",
  mana_cost: 3,
  target: "tile",
  range: 7,
  requires_line_of_sight: true,
  cooldown_remaining: 0,
  disabled: false,
};

describe("line", () => {
  // Same cases as backend/tests/test_geometry_and_map.py, so both sides agree.
  it("matches the engine's Bresenham line", () => {
    expect(line([0, 0], [3, 0])).toEqual([
      [1, 0],
      [2, 0],
      [3, 0],
    ]);
    expect(line([0, 0], [2, 2])).toEqual([
      [1, 1],
      [2, 2],
    ]);
    expect(line([1, 1], [1, 1])).toEqual([]);
    expect(line([0, 0], [1, 4])).toHaveLength(4);
  });

  it("measures distance in king moves", () => {
    expect(distance([0, 0], [3, -2])).toBe(3);
  });
});

describe("targeting", () => {
  const map = [
    "..........", //
    "..#.......",
    "..........",
  ];

  it("blocks line of sight with walls", () => {
    const state = game(map, []);
    expect(hasLineOfSight(state, [0, 1], [4, 1])).toBe(false);
    expect(hasLineOfSight(state, [0, 0], [4, 0])).toBe(true);
  });

  it("explains why a target is invalid", () => {
    const state = game(map, [entity(1, [0, 1], "player")]);
    expect(targetProblem(state, firebolt, [4, 1])).toBe("no line of sight");
    expect(targetProblem(state, firebolt, [2, 1])).toBe("invalid target tile");
    expect(targetProblem(state, firebolt, [9, 0])).toBe("out of range");
    expect(targetProblem(state, { ...firebolt, target: "entity" }, [3, 0])).toBe(
      "no creature there",
    );
    expect(targetProblem(state, firebolt, [3, 0])).toBeNull();
  });

  it("lists valid enemy targets nearest first", () => {
    const state = game(map, [
      entity(1, [0, 0], "player"),
      entity(2, [5, 0], "enemy"),
      entity(3, [2, 0], "enemy"),
      entity(4, [4, 1], "enemy"), // the line to it passes through the wall at (2, 1)
      entity(5, [1, 1], "player"),
    ]);
    expect(validTargets(state, firebolt).map((e) => e.id)).toEqual([3, 2]);
  });
});

describe("drawing helpers", () => {
  it("classifies wall tiles by what is next to them", () => {
    const state = game(["#####", "#####", "##.##", "#####"], []);
    expect(tileKind(state, 2, 2)).toBe("floor");
    expect(tileKind(state, 2, 1)).toBe("wall_face"); // floor directly below
    expect(tileKind(state, 1, 3)).toBe("wall_top"); // diagonal to the floor
    expect(tileKind(state, 0, 0)).toBe("void"); // solid rock
    expect(tileKind(game(["#>#"], []), 1, 0)).toBe("stairs");
  });

  it("keeps the camera centred but inside the map", () => {
    expect(cameraOrigin(24, 30, 48)).toBe(9);
    expect(cameraOrigin(2, 30, 48)).toBe(0);
    expect(cameraOrigin(46, 30, 48)).toBe(18);
    expect(cameraOrigin(5, 48, 48)).toBe(0); // whole map visible
  });
});
