// The leaderboard on the "You died" screen, and the browser's identity for it.
//
// Players are told apart by a random id this browser keeps in localStorage (see
// backend/spellforge/server/leaderboard.py for why not the IP address). Names come from the
// players themselves, so they are always inserted with textContent.

import { el } from "./forge";
import type { LeaderboardEntry, LeaderboardMessage } from "./protocol";

const ID_KEY = "spellforge.playerId";
const NAME_KEY = "spellforge.playerName";
export const MAX_NAME_LENGTH = 20;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage unavailable: the id lasts for this page only.
  }
}

let sessionId: string | null = null;

/** This browser's player id, created on first use. */
export function playerId(): string {
  const stored = read(ID_KEY);
  if (stored && /^[A-Za-z0-9-]{8,64}$/.test(stored)) return stored;
  // crypto.randomUUID needs a secure context (https or localhost); fall back to random hex.
  sessionId ??=
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
          b.toString(16).padStart(2, "0"),
        ).join("");
  write(ID_KEY, sessionId);
  return sessionId;
}

export function storedName(): string | null {
  return read(NAME_KEY);
}

export class LeaderboardView {
  private readonly root: HTMLElement;
  private readonly setName: (name: string) => void;
  private last: LeaderboardMessage | null = null;
  private editing = false;
  private error = "";

  /** `setName` sends the chosen name to the server. */
  constructor(root: HTMLElement, setName: (name: string) => void) {
    this.root = root;
    this.setName = setName;
  }

  clear(): void {
    this.last = null;
    this.editing = false;
    this.error = "";
    this.root.replaceChildren();
  }

  show(message: LeaderboardMessage): void {
    // A reply to "set_name" has no run summary: keep the one from the death message.
    const summary = message.run === undefined ? this.last : message;
    this.last = { ...message, recorded: summary?.recorded, new_best: summary?.new_best };
    if (message.name) write(NAME_KEY, message.name);
    this.editing = false;
    this.error = "";
    this.render();
  }

  nameRefused(reason: string): void {
    this.error = reason;
    this.render();
  }

  private render(): void {
    const data = this.last;
    if (!data) return;
    const parts: HTMLElement[] = [];
    if (data.recorded === false) {
      parts.push(el("p", "leaderboard-note", "Dev tools were used, so this run is not ranked."));
    } else if (data.new_best) {
      parts.push(el("p", "leaderboard-best", "New personal best!"));
    }
    if (!data.name || this.editing) parts.push(this.nameForm(data.name));
    parts.push(this.table(data));
    if (data.name && !this.editing) {
      const rename = el("button", "ghost leaderboard-rename", `Playing as ${data.name} · change`);
      rename.type = "button";
      rename.addEventListener("click", () => {
        this.editing = true;
        this.render();
      });
      parts.push(rename);
    }
    this.root.replaceChildren(...parts);
    this.root.querySelector("input")?.focus();
  }

  private nameForm(current: string | null): HTMLElement {
    const form = el("form", "leaderboard-name");
    const input = el("input", "");
    input.maxLength = MAX_NAME_LENGTH;
    input.placeholder = "Your name";
    input.value = current ?? storedName() ?? "";
    input.setAttribute("aria-label", "Your name for the leaderboard");
    const save = el("button", "", "Save");
    save.type = "submit";
    form.append(
      el("label", "", current ? "Change your name" : "Put your name on the leaderboard"),
      input,
      save,
    );
    if (this.error) form.append(el("p", "leaderboard-error", this.error));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const name = input.value.trim();
      if (name) this.setName(name);
    });
    return form;
  }

  private table(data: LeaderboardMessage): HTMLElement {
    const table = el("table", "leaderboard-table");
    const head = el("tr", "");
    for (const title of ["#", "Name", "Depth", "Kills", "Turns", "Spells"]) {
      head.append(el("th", "", title));
    }
    table.append(head);
    for (const entry of data.entries) table.append(row(entry));
    if (data.you) {
      const gap = el("tr", "leaderboard-gap");
      const cell = el("td", "", "…");
      cell.colSpan = 6;
      gap.append(cell);
      table.append(gap, row(data.you));
    }
    if (data.entries.length === 0) {
      const empty = el("tr", "");
      const cell = el("td", "muted", "No runs yet.");
      cell.colSpan = 6;
      empty.append(cell);
      table.append(empty);
    }
    const wrap = el("div", "leaderboard-scroll");
    wrap.append(table);
    return wrap;
  }
}

function row(entry: LeaderboardEntry): HTMLElement {
  const tr = el("tr", entry.is_you ? "you" : "");
  const spells = el("td", "", String(entry.spells.length));
  spells.title = entry.spells.join(", ") || "No forged spells";
  tr.append(
    el("td", "", String(entry.rank)),
    el("td", entry.name ? "" : "muted", entry.name ?? "anonymous"),
    el("td", "", String(entry.depth)),
    el("td", "", String(entry.kills)),
    el("td", "", String(entry.turns)),
    spells,
  );
  return tr;
}
