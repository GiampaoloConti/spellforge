// The Dungeon Master card: shows the counter-monster being designed, then what it is.

import { creatureSprite } from "./atlas";
import { details, el } from "./forge";
import { changeList, DUNGEON_MASTER_STEPS, PipelineView, stageMessage } from "./pipeline";
import type { DungeonMasterDone, StageDetails } from "./protocol";

const PREVIEW_SCALE = 4;

export class DungeonMasterPanel {
  private readonly root: HTMLElement;
  private readonly status: HTMLElement;
  private readonly message: HTMLElement;
  private readonly result: HTMLElement;
  private readonly idle: HTMLElement;
  private readonly pipeline: PipelineView;

  constructor(root: HTMLElement) {
    this.root = root;
    this.status = query(root, "#dm-status");
    this.message = query(root, "#dm-message");
    this.result = query(root, "#dm-result");
    this.idle = query(root, "#dm-idle");
    this.pipeline = new PipelineView(query(root, "#dm-steps"));
  }

  setAvailable(available: boolean): void {
    this.root.hidden = !available;
  }

  reset(): void {
    this.status.hidden = true;
    this.result.hidden = true;
    this.result.replaceChildren();
    this.idle.hidden = false;
  }

  started(): void {
    this.idle.hidden = true;
    this.result.hidden = true;
    this.status.hidden = false;
    this.message.textContent = "The Dungeon Master has been watching how you fight…";
    this.pipeline.reset(DUNGEON_MASTER_STEPS);
  }

  progress(details: StageDetails, message: string): void {
    this.message.textContent = stageMessage(details.stage, message);
    this.pipeline.update(details, message);
  }

  done(result: DungeonMasterDone): void {
    this.status.hidden = true;
    const monster = result.monster;
    const header = el("div", "dm-monster");
    const preview = document.createElement("canvas");
    preview.className = "dm-preview";
    preview.width = preview.height = 16 * PREVIEW_SCALE;
    const art = monster.sprite ? creatureSprite(monster.sprite, false) : null;
    const ctx = preview.getContext("2d");
    if (art && ctx) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(art, 0, 0, preview.width, preview.height);
    }
    const title = el("div", "");
    title.append(
      el("p", "dm-name", monster.name),
      el("p", "muted", `HP ${monster.max_hp} · attack ${monster.attack} · from depth ${monster.first_depth}`),
    );
    header.append(preview, title);

    const body: HTMLElement[] = [
      header,
      el("p", "dm-taunt", `“${monster.taunt}”`),
      labelled("Counters", monster.counters),
      labelled("Weakness", monster.weakness),
    ];
    if (result.review) {
      body.push(labelled(`Balancer (${result.review.verdict})`, result.review.rationale));
      if (result.review.changes.length) body.push(changeList(result.review.changes));
    }
    body.push(details("", result.source), el("p", "muted forge-meta", `${result.seconds}s · $${result.cost_usd.toFixed(3)}`));
    this.result.replaceChildren(...body);
    this.result.hidden = false;
  }

  failed(message: string): void {
    this.status.hidden = true;
    this.result.replaceChildren(el("p", "forge-problems", message));
    this.result.hidden = false;
  }
}

function query<T extends HTMLElement>(root: ParentNode, selector: string): T {
  const node = root.querySelector<T>(selector);
  if (!node) throw new Error(`missing element ${selector}`);
  return node;
}

function labelled(label: string, text: string): HTMLElement {
  const p = el("p", "dm-line");
  p.append(el("strong", "", `${label}: `), document.createTextNode(text));
  return p;
}
