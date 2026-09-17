import { describe, expect, it } from "vitest";
import { keyToCommand } from "./input";

describe("keyToCommand", () => {
  it("maps movement keys, including diagonals and the numpad", () => {
    expect(keyToCommand("ArrowUp")).toEqual({ type: "move", dx: 0, dy: -1 });
    expect(keyToCommand("KeyC")).toEqual({ type: "move", dx: 1, dy: 1 });
    expect(keyToCommand("Numpad7")).toEqual({ type: "move", dx: -1, dy: -1 });
  });

  it("maps digits to spells and numpad 5 to wait", () => {
    expect(keyToCommand("Digit1")).toEqual({ type: "spell", index: 0 });
    expect(keyToCommand("Digit9")).toEqual({ type: "spell", index: 8 });
    expect(keyToCommand("Numpad5")).toEqual({ type: "wait" });
    expect(keyToCommand("Digit0")).toBeNull();
  });

  it("maps targeting and game keys", () => {
    expect(keyToCommand("Enter")).toEqual({ type: "confirm" });
    expect(keyToCommand("Escape")).toEqual({ type: "cancel" });
    expect(keyToCommand("Tab")).toEqual({ type: "next_target" });
    expect(keyToCommand("KeyN")).toEqual({ type: "new_game" });
    expect(keyToCommand("KeyX")).toBeNull();
  });
});
