// Maps keyboard keys to game commands. Pure, so it is unit-tested.

export type Command =
  | { type: "move"; dx: number; dy: number }
  | { type: "wait" }
  | { type: "spell"; index: number } // 0-based position in the spellbook
  | { type: "confirm" }
  | { type: "cancel" }
  | { type: "next_target" }
  | { type: "new_game" }
  | { type: "focus_forge" };

// `Record<K, V>` is an object type whose keys are K and values are V.
const MOVE_KEYS: Record<string, [number, number]> = {
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  KeyW: [0, -1],
  KeyS: [0, 1],
  KeyA: [-1, 0],
  KeyD: [1, 0],
  KeyQ: [-1, -1],
  KeyE: [1, -1],
  KeyZ: [-1, 1],
  KeyC: [1, 1],
  Numpad8: [0, -1],
  Numpad2: [0, 1],
  Numpad4: [-1, 0],
  Numpad6: [1, 0],
  Numpad7: [-1, -1],
  Numpad9: [1, -1],
  Numpad1: [-1, 1],
  Numpad3: [1, 1],
};

/**
 * `code` is the physical key (KeyW is the same key on QWERTY and AZERTY layouts), which
 * is what we want for movement. Returns null for keys the game does not use.
 */
export function keyToCommand(code: string): Command | null {
  const move = MOVE_KEYS[code];
  if (move) return { type: "move", dx: move[0], dy: move[1] };

  const digit = /^Digit([1-9])$/.exec(code);
  if (digit) return { type: "spell", index: Number(digit[1]) - 1 };

  switch (code) {
    case "Period":
    case "Space":
    case "Numpad5":
      return { type: "wait" };
    case "Enter":
    case "NumpadEnter":
      return { type: "confirm" };
    case "Escape":
      return { type: "cancel" };
    case "Tab":
      return { type: "next_target" };
    case "KeyN":
      return { type: "new_game" };
    case "KeyF":
      return { type: "focus_forge" };
    default:
      return null;
  }
}
