// A live view of an agent pipeline: one row per agent, its state, and what it produced.
//
// Rows are driven by progress messages. The agent team sends explicit `done` flags because its
// agents overlap (the Coder and Artist start while the Balancer is still reviewing); simpler
// pipelines just move forward, so starting a later step completes the earlier ones.

import type { BalanceChange, Stage, StageDetails, Verdict } from "./protocol";

export interface StepDef {
  stage: Stage;
  label: string;
  optional?: boolean; // hidden until the pipeline actually uses it
}

export const TEAM_STEPS: StepDef[] = [
  { stage: "designing", label: "Designer" },
  { stage: "balancing", label: "Balancer" },
  { stage: "coding", label: "Coder" },
  { stage: "drawing", label: "Artist", optional: true },
  { stage: "testing", label: "Tester" },
  { stage: "loading", label: "Binding to your spellbook" },
];

export const SINGLE_STEPS: StepDef[] = [
  { stage: "writing", label: "Spell Writer" },
  { stage: "testing", label: "Tester" },
  { stage: "loading", label: "Binding to your spellbook" },
];

export const DUNGEON_MASTER_STEPS: StepDef[] = [
  { stage: "designing", label: "Dungeon Master" },
  { stage: "balancing", label: "Balancer" },
  { stage: "coding", label: "Coder" },
  { stage: "drawing", label: "Artist", optional: true },
  { stage: "testing", label: "Tester" },
];

type StepState = "pending" | "active" | "done";

interface Step extends StepDef {
  state: StepState;
  detail: string;
  verdict?: Verdict;
  changes: BalanceChange[];
  fixing: boolean;
  seen: boolean;
}

const VERDICT_LABEL: Record<Verdict, string> = {
  approve: "approved",
  adjust: "adjusted",
  reject: "rejected",
};

export class PipelineView {
  private steps: Step[] = [];
  private readonly list: HTMLElement;
  private explicitDone = false;

  constructor(list: HTMLElement) {
    this.list = list;
  }

  reset(defs: StepDef[]): void {
    this.steps = defs.map((def) => ({
      ...def,
      state: "pending",
      detail: "",
      changes: [],
      fixing: false,
      seen: !def.optional,
    }));
    this.explicitDone = false;
    this.render();
  }

  update(details: StageDetails, message: string): void {
    if (details.stage === "retrying") {
      const coder = this.find("coding") ?? this.find("writing");
      const tester = this.find("testing");
      if (tester) {
        tester.state = "pending";
        tester.detail = message;
      }
      if (coder) {
        coder.state = "active";
        coder.fixing = true;
      }
      this.render();
      return;
    }
    const step = this.find(details.stage);
    if (!step) return;
    step.seen = true;
    if (details.done) {
      this.explicitDone = true;
      step.state = "done";
      step.fixing = false;
    } else if (step.state !== "done" || details.stage === "coding") {
      step.state = "active";
    }
    if (details.detail) step.detail = details.detail;
    if (details.verdict) step.verdict = details.verdict;
    if (details.changes) step.changes = details.changes;
    // Pipelines without explicit done flags simply move forward.
    if (!this.explicitDone || details.stage === "loading") {
      const index = this.steps.indexOf(step);
      for (const earlier of this.steps.slice(0, index)) {
        if (earlier.state === "active") earlier.state = "done";
      }
    }
    this.render();
  }

  /** Mark whatever is still running as finished (used when the whole pipeline succeeds). */
  finish(): void {
    for (const step of this.steps) if (step.state === "active") step.state = "done";
    this.render();
  }

  private find(stage: Stage): Step | undefined {
    return this.steps.find((step) => step.stage === stage);
  }

  private render(): void {
    this.list.replaceChildren(
      ...this.steps
        .filter((step) => step.seen)
        .map((step) => {
          const item = document.createElement("li");
          item.className = `pipeline-step ${step.state}`;
          const head = document.createElement("div");
          head.className = "pipeline-head";
          const label = document.createElement("span");
          label.className = "pipeline-label";
          label.textContent = step.fixing ? `${step.label} (fixing)` : step.label;
          head.append(label);
          if (step.verdict) {
            const badge = document.createElement("span");
            badge.className = `verdict ${step.verdict}`;
            badge.textContent = VERDICT_LABEL[step.verdict];
            head.append(badge);
          }
          item.append(head);
          if (step.detail) {
            const detail = document.createElement("p");
            detail.className = "pipeline-detail";
            detail.textContent = step.detail;
            item.append(detail);
          }
          if (step.changes.length) item.append(changeList(step.changes));
          return item;
        }),
    );
  }
}

/** "cooldown 3 → 4: reason" lines for the Balancer's adjustments. */
export function changeList(changes: BalanceChange[]): HTMLElement {
  const list = document.createElement("ul");
  list.className = "balance-changes";
  for (const change of changes) {
    const item = document.createElement("li");
    const what = document.createElement("strong");
    what.textContent = `${change.field}: ${change.before} → ${change.after}`;
    item.append(what, document.createTextNode(` ${change.reason}`));
    list.append(item);
  }
  return list;
}
