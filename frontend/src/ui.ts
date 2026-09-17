// The sidebar: stats, spell list and message log, built with DOM elements.
//
// Text from the server is always set with `textContent`, never `innerHTML`: log lines
// will soon contain text written by AI-generated plugins and must not become markup.

import { player } from "./grid";
import type { GameState } from "./protocol";

/** Create an element with a class and optional text: el("li", "log-line", "Hello"). */
function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  // `K extends keyof HTMLElementTagNameMap` is a generic: el("button") returns an
  // HTMLButtonElement, el("li") an HTMLLIElement, and so on.
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function meter(label: string, value: number, max: number, kind: string): HTMLElement {
  const wrap = el("div", "meter");
  const head = el("div", "meter-head");
  head.append(el("span", "", label), el("span", "meter-value", `${value} / ${max}`));
  const bar = el("div", `meter-bar ${kind}`);
  const fill = el("div", "meter-fill");
  fill.style.width = `${max > 0 ? (100 * Math.max(0, value)) / max : 0}%`;
  bar.append(fill);
  wrap.append(head, bar);
  return wrap;
}

export function renderStats(container: HTMLElement, state: GameState): void {
  const me = player(state);
  const hp = me?.hp ?? 0;
  const statuses = me?.statuses.map((s) => s.id).join(", ");
  container.replaceChildren(
    meter("Health", hp, me?.max_hp ?? 20, "hp"),
    meter("Mana", me?.mana ?? 0, me?.max_mana ?? 10, "mana"),
    el("p", "muted", `Depth ${state.depth} · Turn ${state.turn}${statuses ? ` · ${statuses}` : ""}`),
  );
}

export function renderSpells(
  list: HTMLElement,
  state: GameState,
  selectedId: string | null,
  onSelect: (index: number) => void,
  newSpellIds: ReadonlySet<string> = new Set(),
): void {
  const mana = player(state)?.mana ?? 0;
  list.replaceChildren(
    ...state.spells.map((spell, index) => {
      const button = el("button", "spell");
      button.type = "button";
      button.title = spell.description;
      const unavailable = spell.disabled || spell.cooldown_remaining > 0 || mana < spell.mana_cost;
      button.classList.toggle("unavailable", unavailable);
      button.classList.toggle("selected", spell.id === selectedId);

      const status = spell.disabled
        ? "disabled"
        : spell.cooldown_remaining > 0
          ? `cooldown ${spell.cooldown_remaining}`
          : spell.target === "self"
            ? "self"
            : `range ${spell.range}`;
      const name = el("span", "spell-name", spell.name);
      if (newSpellIds.has(spell.id)) name.append(el("span", "new-badge", "new"));
      button.append(
        el("kbd", "", String(index + 1)),
        name,
        el("span", "spell-cost", `${spell.mana_cost} mana`),
        el("span", "spell-meta", status),
      );
      button.addEventListener("click", () => onSelect(index));
      const item = el("li");
      item.append(button);
      return item;
    }),
  );
}

export type LogKind = "info" | "error" | "system";

export class Log {
  private readonly list: HTMLElement;
  private static readonly MAX_LINES = 200;

  constructor(list: HTMLElement) {
    this.list = list;
  }

  add(lines: string[], kind: LogKind = "info"): void {
    for (const line of lines) this.list.append(el("li", `log-line ${kind}`, line));
    while (this.list.childElementCount > Log.MAX_LINES) this.list.firstElementChild?.remove();
    this.list.scrollTop = this.list.scrollHeight;
  }

  clear(): void {
    this.list.replaceChildren();
  }
}
