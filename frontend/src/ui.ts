// The dock under the board: health, mana, shards, the spell hotbar and the message log,
// built with DOM elements.
//
// Text from the server is always set with `textContent`, never `innerHTML`: log lines
// can contain text written by AI-generated plugins and must not become markup.

import { itemSprite } from "./atlas";
import { player } from "./grid";
import type { GameState } from "./protocol";

export const SHARD = "arcane_shard";

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
  const wrap = el("div", `meter ${kind}`);
  wrap.title = label;
  const bar = el("div", "meter-bar");
  const fill = el("div", "meter-fill");
  fill.style.width = `${max > 0 ? (100 * Math.max(0, value)) / max : 0}%`;
  bar.append(fill, el("span", "meter-value", `${label} ${value}/${max}`));
  wrap.append(bar);
  return wrap;
}

/** A small crisp image of the shard sprite, for text-sized UI. */
export function shardIcon(): HTMLImageElement {
  const icon = el("img", "shard-icon");
  icon.alt = "";
  icon.src = itemSprite(SHARD)?.toDataURL() ?? "";
  return icon;
}

export function shardCount(state: GameState): number {
  return state.inventory[SHARD] ?? 0;
}

export function renderStats(container: HTMLElement, state: GameState): void {
  const me = player(state);
  const shards = el("span", "chip shards");
  shards.title = "Arcane shards: each one lets you forge a spell";
  shards.append(shardIcon(), el("span", "", `${shardCount(state)}`));
  const statuses = el("span", "statuses muted", me?.statuses.map((s) => s.id).join(", ") ?? "");
  container.replaceChildren(
    meter("HP", me?.hp ?? 0, me?.max_hp ?? 20, "hp"),
    meter("Mana", me?.mana ?? 0, me?.max_mana ?? 10, "mana"),
    shards,
    statuses,
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
        el("span", "spell-cost", `${spell.mana_cost}`),
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
