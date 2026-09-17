// Entry point: wires the connection, input, renderer and sidebar together.
// All game rules live on the server; this file only keeps UI state (e.g. targeting).

import "./style.css";
import { GameConnection, serverUrl, type ConnectionStatus } from "./connection";
import { Effects } from "./effects";
import { player, targetProblem, validTargets } from "./grid";
import { keyToCommand, type Command } from "./input";
import type { ActionPayload, GameState, Point, ServerMessage } from "./protocol";
import { BOB_MS, describeTile, Renderer, type Targeting } from "./renderer";
import { Log, renderSpells, renderStats } from "./ui";

/** Look up a required element; fail loudly if index.html and this file disagree. */
function $<T extends HTMLElement>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) throw new Error(`missing element ${selector}`);
  return node;
}

const canvas = $<HTMLCanvasElement>("#board");
const boardWrap = $<HTMLElement>("#board-wrap");
const overlay = $<HTMLElement>("#overlay");
const hoverInfo = $<HTMLElement>("#hover-info");
const connectionPill = $<HTMLElement>("#connection");
const runInfo = $<HTMLElement>("#run-info");
const stats = $<HTMLElement>("#stats");
const spells = $<HTMLElement>("#spells");
const targetingHint = $<HTMLElement>("#targeting-hint");

const renderer = new Renderer(canvas);
const effects = new Effects();
const log = new Log($<HTMLElement>("#log"));

// ---- UI state ------------------------------------------------------------------

let state: GameState | null = null;
let targeting: Targeting | null = null;
let awaitingReply = false; // one action at a time: ignore input until the server answers
let startingNewGame = false;
let hadConnection = false;

const connection = new GameConnection(serverUrl(), {
  onOpen: () => {
    if (hadConnection) log.add(["Reconnected. Starting a new run."], "system");
    hadConnection = true;
    newGame();
  },
  onMessage: handleMessage,
  onStatus: showConnection,
});

function seedFromUrl(): number | null {
  const seed = new URLSearchParams(location.search).get("seed");
  return seed !== null && /^\d+$/.test(seed) ? Number(seed) : null;
}

function newGame(): void {
  targeting = null;
  startingNewGame = true;
  awaitingReply = connection.send({ type: "new_game", seed: seedFromUrl() });
}

function sendAction(action: ActionPayload): void {
  if (!state || awaitingReply || state.status !== "playing") return;
  awaitingReply = connection.send({ type: "action", action });
}

// ---- server messages ------------------------------------------------------------

function handleMessage(message: ServerMessage): void {
  awaitingReply = false;
  // Narrowing: inside this `if`, TypeScript knows `message` is the error variant.
  if (message.type === "error") {
    log.add([`Can't: ${message.message}`], "error");
    return;
  }
  if (startingNewGame) {
    log.clear();
    renderer.reset();
    startingNewGame = false;
  }
  state = message.state;
  effects.addEvents(message.events, performance.now());
  log.add(message.log);
  renderer.resize(state, boardWrap);
  refresh();
}

function showConnection(status: ConnectionStatus): void {
  connectionPill.textContent = { connecting: "connecting…", open: "online", closed: "offline" }[
    status
  ];
  connectionPill.dataset.status = status;
  if (status === "closed") awaitingReply = false;
}

// ---- input -------------------------------------------------------------------------

function handleCommand(command: Command): void {
  if (command.type === "new_game") {
    const midRun = state?.status === "playing" && state.turn > 1;
    if (!midRun || confirm("Abandon this run and start a new game?")) newGame();
    return;
  }
  if (!state) return;

  if (targeting) {
    switch (command.type) {
      case "move":
        targeting.cursor = clampToMap(state, [
          targeting.cursor[0] + command.dx,
          targeting.cursor[1] + command.dy,
        ]);
        break;
      case "confirm":
        castAt(targeting.cursor);
        break;
      case "cancel":
        targeting = null;
        break;
      case "next_target":
        cycleTarget(state, targeting);
        break;
      case "spell":
        selectSpell(command.index);
        break;
    }
    refresh();
    return;
  }

  switch (command.type) {
    case "move":
      sendAction({ kind: "move", dx: command.dx, dy: command.dy });
      break;
    case "wait":
      sendAction({ kind: "wait" });
      break;
    case "spell":
      selectSpell(command.index);
      break;
  }
}

function selectSpell(index: number): void {
  if (!state || state.status !== "playing") return;
  const spell = state.spells[index];
  if (!spell) return;
  if (targeting?.spell.id === spell.id) {
    targeting = null; // pressing the same key again cancels
    refresh();
    return;
  }
  const me = player(state);
  const problem = spell.disabled
    ? `${spell.name} is disabled`
    : spell.cooldown_remaining > 0
      ? `${spell.name} is on cooldown`
      : me && me.mana < spell.mana_cost
        ? `not enough mana for ${spell.name}`
        : null;
  if (problem) {
    log.add([`Can't: ${problem}`], "error");
    return;
  }
  if (spell.target === "self") {
    targeting = null;
    sendAction({ kind: "cast", spell: spell.id, target: null });
    refresh();
    return;
  }
  const nearest = validTargets(state, spell)[0];
  targeting = { spell, cursor: nearest?.pos ?? me?.pos ?? [0, 0] };
  refresh();
}

function castAt(target: Point): void {
  if (!state || !targeting) return;
  const problem = targetProblem(state, targeting.spell, target);
  if (problem) {
    log.add([`Can't: ${problem}`], "error");
    return;
  }
  const spell = targeting.spell;
  targeting = null;
  sendAction({ kind: "cast", spell: spell.id, target });
}

function cycleTarget(current: GameState, active: Targeting): void {
  const targets = validTargets(current, active.spell);
  if (targets.length === 0) return;
  const index = targets.findIndex(
    (e) => e.pos[0] === active.cursor[0] && e.pos[1] === active.cursor[1],
  );
  active.cursor = targets[(index + 1) % targets.length]!.pos;
}

function clampToMap(current: GameState, [x, y]: Point): Point {
  const width = current.map[0]?.length ?? 1;
  return [
    Math.min(Math.max(x, 0), width - 1),
    Math.min(Math.max(y, 0), current.map.length - 1),
  ];
}

window.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const command = keyToCommand(event.code);
  if (!command) return;
  event.preventDefault();
  handleCommand(command);
});

canvas.addEventListener("mousemove", (event) => {
  if (!state) return;
  const tile = renderer.tileAt(state, event.clientX, event.clientY);
  hoverInfo.textContent = tile ? describeTile(state, tile) : "";
  if (targeting && tile) {
    targeting.cursor = tile;
    requestDraw();
  }
});

canvas.addEventListener("click", (event) => {
  if (!state || !targeting) return;
  const tile = renderer.tileAt(state, event.clientX, event.clientY);
  if (tile) castAt(tile);
  refresh();
});

canvas.addEventListener("contextmenu", (event) => {
  if (!targeting) return;
  event.preventDefault();
  targeting = null;
  refresh();
});

$<HTMLButtonElement>("#new-game").addEventListener("click", () =>
  handleCommand({ type: "new_game" }),
);
$<HTMLButtonElement>("#overlay-new").addEventListener("click", newGame);

window.addEventListener("resize", () => {
  if (!state) return;
  renderer.resize(state, boardWrap);
  requestDraw();
});

// ---- drawing -----------------------------------------------------------------------

function refresh(): void {
  if (!state) return;
  runInfo.textContent = `seed ${state.seed}`;
  renderStats(stats, state);
  renderSpells(spells, state, targeting?.spell.id ?? null, selectSpell);
  targetingHint.textContent = targeting
    ? `Aiming ${targeting.spell.name}: click or Enter to cast, Tab for next target, Esc to cancel.`
    : "";

  overlay.hidden = state.status === "playing";
  if (state.status !== "playing") {
    $<HTMLElement>("#overlay-title").textContent =
      state.status === "won" ? "Victory" : "You died";
    $<HTMLElement>("#overlay-text").textContent =
      state.status === "won"
        ? `Every monster is dead after ${state.turn} turns.`
        : `The dungeon claimed you on turn ${state.turn}.`;
  }
  requestDraw();
}

let frame = 0;

function requestDraw(): void {
  if (frame === 0) frame = requestAnimationFrame(drawFrame);
}

function drawFrame(now: number): void {
  frame = 0;
  if (!state) return;
  effects.prune(now);
  renderer.draw(state, targeting, effects, now);
  if (effects.active) requestDraw(); // keep animating until effects fade out
}

setInterval(requestDraw, BOB_MS); // idle animation
