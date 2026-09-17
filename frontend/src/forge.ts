// The Arcane Forge panel: the player describes a spell, then watches the agent work.
//
// All text from the server (notes, problems, generated code) goes in with textContent.

import type { ForgeDone, ForgeStage } from "./protocol";

const STEPS: { stage: ForgeStage; label: string }[] = [
  { stage: "writing", label: "Designing and writing the spell" },
  { stage: "testing", label: "Testing it in the sandbox" },
  { stage: "loading", label: "Binding it to your spellbook" },
];

function $<T extends HTMLElement>(root: ParentNode, selector: string): T {
  const node = root.querySelector<T>(selector);
  if (!node) throw new Error(`missing element ${selector}`);
  return node;
}

export class ForgePanel {
  private readonly form: HTMLFormElement;
  private readonly idea: HTMLTextAreaElement;
  private readonly submit: HTMLButtonElement;
  private readonly count: HTMLElement;
  private readonly offline: HTMLElement;
  private readonly status: HTMLElement;
  private readonly message: HTMLElement;
  private readonly timer: HTMLElement;
  private readonly steps: HTMLElement;
  private readonly result: HTMLElement;
  private available = false;
  private working = false;
  private startedAt = 0;
  private tick = 0;

  /** `onSubmit` receives the trimmed idea; it should send the invent message. */
  constructor(root: HTMLElement, onSubmit: (idea: string) => void) {
    this.form = $(root, "#forge-form");
    this.idea = $(root, "#forge-idea");
    this.submit = $(root, "#forge-submit");
    this.count = $(root, "#forge-count");
    this.offline = $(root, "#forge-offline");
    this.status = $(root, "#forge-status");
    this.message = $(root, "#forge-message");
    this.timer = $(root, "#forge-timer");
    this.steps = $(root, "#forge-steps");
    this.result = $(root, "#forge-result");

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      const idea = this.idea.value.trim();
      if (idea.length >= 3 && this.available && !this.working) onSubmit(idea);
    });
    this.idea.addEventListener("input", () => this.updateControls());
    this.idea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        this.form.requestSubmit();
      } else if (event.key === "Escape") {
        this.idea.blur();
      }
    });
    this.updateControls();
  }

  focus(): void {
    this.idea.focus();
  }

  setAvailable(available: boolean, reason: string): void {
    this.available = available;
    this.offline.hidden = available;
    this.offline.textContent = available ? "" : reason;
    this.updateControls();
  }

  started(idea: string): void {
    this.working = true;
    this.startedAt = performance.now();
    this.idea.value = idea;
    this.result.hidden = true;
    this.status.hidden = false;
    this.message.textContent = "The arcane forge takes your idea…";
    this.renderSteps("writing");
    window.clearInterval(this.tick);
    this.tick = window.setInterval(() => this.updateTimer(), 250);
    this.updateTimer();
    this.updateControls();
  }

  progress(stage: ForgeStage, message: string): void {
    this.message.textContent = message;
    this.renderSteps(stage === "retrying" ? "writing" : stage, stage === "retrying");
  }

  done(result: ForgeDone): void {
    this.finish();
    const tokens = Math.round((result.input_tokens + result.output_tokens) / 100) / 10;
    const attempts = result.attempts === 1 ? "1 attempt" : `${result.attempts} attempts`;
    this.showResult("success", `✦ ${result.spell.name}`, [
      el("p", "forge-spell-description", result.spell.description),
      ...result.warnings.map((warning) => el("p", "forge-warning", `⚠ ${warning}`)),
      details(result.notes, result.source),
      el("p", "muted forge-meta", `${attempts} · ${result.seconds}s · ${tokens}k tokens`),
    ]);
    this.idea.value = "";
    this.updateControls();
  }

  failed(message: string, problems: string[] = []): void {
    const wasWorking = this.working;
    this.finish();
    const list = el("ul", "forge-problems");
    list.append(...problems.map((problem) => el("li", "", problem)));
    this.showResult("failure", message, problems.length ? [list] : []);
    if (!wasWorking) this.result.classList.add("brief");
  }

  private finish(): void {
    this.working = false;
    window.clearInterval(this.tick);
    this.status.hidden = true;
    this.updateControls();
  }

  private showResult(kind: "success" | "failure", title: string, body: HTMLElement[]): void {
    this.result.className = `forge-result ${kind}`;
    this.result.replaceChildren(el("p", "forge-result-title", title), ...body);
    this.result.hidden = false;
  }

  private renderSteps(current: ForgeStage, retrying = false): void {
    const index = STEPS.findIndex((step) => step.stage === current);
    this.steps.replaceChildren(
      ...STEPS.map((step, i) => {
        const state = i < index ? "done" : i === index ? "active" : "pending";
        const label = retrying && i === index ? `${step.label} (fixing)` : step.label;
        const item = el("li", `forge-step ${state}`, label);
        return item;
      }),
    );
  }

  private updateTimer(): void {
    const seconds = (performance.now() - this.startedAt) / 1000;
    this.timer.textContent = `${seconds.toFixed(0)}s`;
  }

  private updateControls(): void {
    const length = this.idea.value.trim().length;
    this.count.textContent = `${this.idea.value.length} / 300`;
    this.idea.disabled = !this.available || this.working;
    this.submit.disabled = !this.available || this.working || length < 3;
    this.submit.textContent = this.working ? "Forging…" : "Forge spell";
  }
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Collapsed by default so the spellbook stays in view during play. */
function details(notes: string, source: string): HTMLElement {
  const box = el("details", "forge-code");
  const pre = el("pre", "");
  pre.append(el("code", "", source));
  box.append(
    el("summary", "", "Writer's notes and generated code"),
    el("p", "forge-notes", notes),
    pre,
  );
  return box;
}
