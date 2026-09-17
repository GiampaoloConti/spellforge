// Short-lived visual effects (hit flashes, floating numbers) derived from engine events.

import type { GameEvent, Point } from "./protocol";

export const FLASH_MS = 260;
export const FLOAT_MS = 850;

export interface Flash {
  pos: Point;
  color: string;
  start: number;
}

export interface Floater {
  pos: Point;
  text: string;
  color: string;
  start: number;
}

export class Effects {
  flashes: Flash[] = [];
  floaters: Floater[] = [];

  addEvents(events: GameEvent[], now: number): void {
    for (const event of events) {
      const pos = event.pos;
      switch (event.type) {
        case "damaged":
          if (pos) {
            this.flashes.push({ pos, color: "255, 84, 112", start: now });
            this.floaters.push({ pos, text: `-${event.amount}`, color: "#ff6b81", start: now });
          }
          break;
        case "healed":
          if (pos) {
            this.floaters.push({ pos, text: `+${event.amount}`, color: "#6fdc8c", start: now });
          }
          break;
        case "spell_cast": {
          const target = event.target as Point | undefined;
          if (target) this.flashes.push({ pos: target, color: "180, 140, 255", start: now });
          break;
        }
      }
    }
  }

  prune(now: number): void {
    this.flashes = this.flashes.filter((f) => now - f.start < FLASH_MS);
    this.floaters = this.floaters.filter((f) => now - f.start < FLOAT_MS);
  }

  get active(): boolean {
    return this.flashes.length > 0 || this.floaters.length > 0;
  }
}
