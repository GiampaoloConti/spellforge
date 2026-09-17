// The Arcane Forge panel: the player describes a spell, then watches the agents work.
//
// All text from the server (notes, problems, generated code) goes in with textContent.

import { changeList, PipelineView, SINGLE_STEPS, TEAM_STEPS } from "./pipeline";
import type { ForgeDone, StageDetails, TeamReport } from "./protocol";

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
  private readonly result: HTMLElement;
  private readonly pipeline: PipelineView;
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
    this.result = $(root, "#forge-result");
    this.pipeline = new PipelineView($(root, "#forge-steps"));

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

  started(idea: string, mode: "team" | "single"): void {
    this.working = true;
    this.startedAt = performance.now();
    this.idea.value = idea;
    this.result.hidden = true;
    this.status.hidden = false;
    this.message.textContent = "The arcane forge takes your idea…";
    this.pipeline.reset(mode === "team" ? TEAM_STEPS : SINGLE_STEPS);
    window.clearInterval(this.tick);
    this.tick = window.setInterval(() => this.updateTimer(), 250);
    this.updateTimer();
    this.updateControls();
  }

  progress(details: StageDetails, message: string): void {
    this.message.textContent = message;
    this.pipeline.update(details, message);
  }

  done(result: ForgeDone): void {
    this.pipeline.finish();
    this.finish();
    const tokens = Math.round((result.input_tokens + result.output_tokens) / 100) / 10;
    const attempts = result.attempts === 1 ? "1 attempt" : `${result.attempts} attempts`;
    const cost = result.cost_usd ? ` · $${result.cost_usd.toFixed(3)}` : "";
    this.showResult("success", `✦ ${result.spell.name}`, [
      el("p", "forge-spell-description", result.spell.description),
      ...reviewSummary(result.team),
      ...result.warnings.map((warning) => el("p", "forge-warning", `⚠ ${warning}`)),
      details(result.notes, result.source, result.team),
      el("p", "muted forge-meta", `${attempts} · ${result.seconds}s · ${tokens}k tokens${cost}`),
    ]);
    this.idea.value = "";
    this.updateControls();
  }

  failed(message: string, problems: string[] = [], team: TeamReport | null = null): void {
    const wasWorking = this.working;
    this.finish();
    const list = el("ul", "forge-problems");
    list.append(...problems.map((problem) => el("li", "", problem)));
    this.showResult("failure", message, [
      ...reviewSummary(team),
      ...(problems.length ? [list] : []),
    ]);
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

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The Balancer's verdict, visible without expanding anything. */
function reviewSummary(team: TeamReport | null | undefined): HTMLElement[] {
  const review = team?.review;
  if (!review) return [];
  const label = { approve: "approved", adjust: "adjusted", reject: "rejected" }[review.verdict];
  const line = el("p", "forge-review");
  line.append(el("span", `verdict ${review.verdict}`, `Balancer ${label}`), document.createTextNode(` ${review.rationale}`));
  return review.changes.length ? [line, changeList(review.changes)] : [line];
}

/** Collapsed by default so the spellbook stays in view during play. */
export function details(notes: string, source: string, team: TeamReport | null = null): HTMLElement {
  const box = el("details", "forge-code");
  const pre = el("pre", "");
  pre.append(el("code", "", source));
  box.append(el("summary", "", team ? "How the agents built it" : "Writer's notes and generated code"));
  if (team) box.append(agentTable(team));
  if (notes) box.append(el("p", "forge-notes", notes));
  box.append(pre);
  return box;
}

function agentTable(team: TeamReport): HTMLElement {
  const table = el("table", "agent-table");
  const head = el("tr", "");
  for (const title of ["Agent", "Model", "Time", "Cost"]) head.append(el("th", "", title));
  table.append(head);
  for (const [role, cost] of Object.entries(team.agents)) {
    const row = el("tr", "");
    row.append(
      el("td", "", role.replace("_", " ")),
      el("td", "", cost.model.replace("claude-", "")),
      el("td", "", `${cost.seconds}s`),
      el("td", "", `$${cost.cost_usd.toFixed(3)}`),
    );
    table.append(row);
  }
  const speculation = {
    off: "",
    started: "",
    used: "The Coder's early start paid off: the Balancer kept the numbers.",
    discarded: "The Coder's early draft was discarded: the Balancer changed the numbers.",
    failed: "The Coder's early draft failed and was rewritten.",
  }[team.speculation];
  const wrap = el("div", "");
  wrap.append(table);
  if (speculation) wrap.append(el("p", "muted forge-speculation", speculation));
  return wrap;
}
