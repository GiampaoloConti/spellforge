// Entry point: wires the connection, input, renderer and sidebar together.
// All game rules live on the server; this file only keeps UI state (e.g. targeting).

import "./style.css";
import { clearPluginSprites, registerSprites, sigilSprite } from "./atlas";
import { GameConnection, serverUrl, type ConnectionStatus } from "./connection";
import { Effects } from "./effects";
import { DungeonMasterPanel } from "./dungeonMaster";
import { ForgePanel } from "./forge";
import { InviteGate } from "./gate";
import { LeaderboardView, playerId, storedName } from "./leaderboard";
import { player, targetProblem, validTargets } from "./grid";
import { keyToCommand, type Command } from "./input";
import type { ActionPayload, DevCommand, GameState, Point, ServerMessage } from "./protocol";
import { BOB_MS, describeTile, Renderer, type Targeting } from "./renderer";
import { Log, renderSpells, renderStats, shardCount } from "./ui";

/** Look up a required element; fail loudly if index.html and this file disagree. */
function $<T extends HTMLElement>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) throw new Error(`missing element ${selector}`);
  return node;
}

const canvas = $<HTMLCanvasElement>("#board");
const boardWrap = $<HTMLElement>("#board-wrap");
const overlay = $<HTMLElement>("#overlay");
const caption = $<HTMLElement>("#board-caption");
const connectionPill = $<HTMLElement>("#connection");
const runInfo = $<HTMLElement>("#run-info");
const stats = $<HTMLElement>("#stats");
const spells = $<HTMLElement>("#spells");
const banner = $<HTMLElement>("#banner");

drawBrand();

const renderer = new Renderer(canvas);
const effects = new Effects();
const log = new Log($<HTMLElement>("#log"));
const forge = new ForgePanel($<HTMLElement>("#forge"), (idea) => {
  connection.send({ type: "invent", idea });
});
const dungeonMaster = new DungeonMasterPanel($<HTMLElement>("#dm"));
const leaderboard = new LeaderboardView($<HTMLElement>("#leaderboard"), (name) => {
  connection.send({ type: "set_name", name });
});

// ---- UI state ------------------------------------------------------------------

let state: GameState | null = null;
let targeting: Targeting | null = null;
let awaitingReply = false; // one action at a time: ignore input until the server answers
let startingNewGame = false;
let hadConnection = false;
let hoverText = "";
const newSpellIds = new Set<string>(); // forged spells not cast yet, shown with a badge

const gate = new InviteGate($<HTMLElement>("#gate"), (code) => {
  connection.send({ type: "unlock", code });
});

// The server greets every connection with "welcome" (or "locked" first, if it needs an
// invite code); the run starts on "welcome".
const connection = new GameConnection(serverUrl(), {
  onOpen: () => {
    if (hadConnection) log.add(["Reconnected. Starting a new run."], "system");
    hadConnection = true;
    gate.reset();
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
  // Narrowing: inside each branch, TypeScript knows exactly which variant `message` is.
  if (message.type === "locked") {
    gate.locked(message.error);
    return;
  }
  if (message.type === "welcome") {
    gate.unlocked();
    forge.setAvailable(message.forge_available, message.forge_status);
    dungeonMaster.setAvailable(message.dungeon_master);
    connection.send({ type: "identify", player_id: playerId(), name: storedName() });
    newGame();
    return;
  }
  if (message.type === "leaderboard") {
    leaderboard.show(message);
    return;
  }
  if (message.type === "forge") {
    handleForge(message);
    return;
  }
  if (message.type === "dungeon_master") {
    handleDungeonMaster(message);
    return;
  }
  awaitingReply = false; // replies to our own new_game/action messages
  if (message.type === "error") {
    log.add([`Can't: ${message.message}`], "error");
    const refusedName = /^can't use that name: (.*)$/.exec(message.message);
    if (refusedName) leaderboard.nameRefused(refusedName[1]!);
    return;
  }
  if (startingNewGame) {
    leaderboard.clear();
    log.clear();
    renderer.reset();
    dungeonMaster.reset();
    clearPluginSprites();
    newSpellIds.clear();
    startingNewGame = false;
  }
  registerSprites(message.sprites);
  for (const event of message.events) {
    if (event.type === "level_started") {
      renderer.reset();
      showBanner(`Depth ${event.depth}`);
    } else if (event.type === "level_cleared") {
      showBanner("Stairs down opened");
    } else if (event.type === "item_picked_up") {
      showBanner("Arcane shard found");
    }
  }
  state = message.state;
  effects.addEvents(message.events, performance.now());
  log.add(message.log);
  renderer.resize(state, boardWrap);
  refresh();
}

// `Extract<Union, Shape>` picks the union members matching Shape: here, the forge messages.
function handleForge(message: Extract<ServerMessage, { type: "forge" }>): void {
  switch (message.status) {
    case "started":
      forge.started(message.idea, message.mode);
      log.add([`The forge consumes a shard and begins work on: “${message.idea}”`], "system");
      adoptState(message.state);
      break;
    case "working":
      forge.progress(message, message.message);
      break;
    case "failed":
      forge.failed(message.message, message.problems, message.team ?? null);
      log.add([message.message], "error");
      if (message.state) adoptState(message.state);
      break;
    case "done":
      forge.done(message);
      newSpellIds.add(message.spell.id);
      registerSprites(message.sprites);
      log.add([`✦ ${message.message}`], "system");
      adoptState(message.state);
      break;
  }
}

/** A state pushed alongside a forge update (not a reply to the player's own action). */
function adoptState(next: GameState): void {
  if (!state || startingNewGame) return;
  state = next;
  refresh();
}

function handleDungeonMaster(message: Extract<ServerMessage, { type: "dungeon_master" }>): void {
  switch (message.status) {
    case "started":
      dungeonMaster.started();
      log.add([message.message], "system");
      break;
    case "working":
      dungeonMaster.progress(message, message.message);
      break;
    case "failed":
      dungeonMaster.failed(message.message);
      log.add([message.message], "error");
      break;
    case "done":
      registerSprites(message.sprites);
      dungeonMaster.done(message);
      log.add([message.message, `“${message.monster.taunt}”`], "system");
      showBanner(`The ${message.monster.name} awaits below`);
      break;
  }
}

function showBanner(text: string): void {
  banner.textContent = text;
  banner.classList.remove("show");
  void banner.offsetWidth; // restart the CSS animation
  banner.classList.add("show");
}

function showConnection(status: ConnectionStatus): void {
  connectionPill.textContent = { connecting: "connecting…", open: "online", closed: "offline" }[
    status
  ];
  connectionPill.title = status === "closed" ? "Lost connection to the server; retrying…" : "";
  connectionPill.dataset.status = status;
  if (status === "closed") awaitingReply = false;
}

// ---- input -------------------------------------------------------------------------

function handleCommand(command: Command): void {
  if (command.type === "focus_forge") {
    targeting = null;
    forge.focus();
    refresh();
    return;
  }
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
    newSpellIds.delete(spell.id);
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
  newSpellIds.delete(spell.id);
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
  // Typing in the forge box must not move the wizard.
  const target = event.target;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) return;
  const command = keyToCommand(event.code);
  if (!command) return;
  event.preventDefault();
  handleCommand(command);
});

canvas.addEventListener("mousemove", (event) => {
  if (!state) return;
  const tile = renderer.tileAt(state, event.clientX, event.clientY);
  hoverText = tile ? describeTile(state, tile) : "";
  updateCaption();
  if (targeting && tile) {
    targeting.cursor = tile;
    requestDraw();
  }
});

canvas.addEventListener("mouseleave", () => {
  hoverText = "";
  updateCaption();
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

// The board fills whatever space the layout gives it, so follow the wrapper's size.
new ResizeObserver(() => {
  if (!state) return;
  renderer.resize(state, boardWrap);
  requestDraw();
}).observe(boardWrap);

// ---- drawing -----------------------------------------------------------------------

function refresh(): void {
  if (!state) return;
  runInfo.textContent = `Depth ${state.depth} · Turn ${state.turn} · Seed ${state.seed}`;
  renderStats(stats, state);
  renderSpells(spells, state, targeting?.spell.id ?? null, selectSpell, newSpellIds);
  forge.setShards(shardCount(state));
  updateCaption();

  overlay.hidden = state.status === "playing";
  if (state.status === "lost") {
    $<HTMLElement>("#overlay-title").textContent = "You died";
    $<HTMLElement>("#overlay-text").textContent =
      `The dungeon claimed you on depth ${state.depth}, after ${state.turn} turns ` +
      `and ${state.kills} ${state.kills === 1 ? "kill" : "kills"}.`;
  }
  requestDraw();
}

/** One line over the bottom of the board: the aiming hint wins over the hover readout. */
function updateCaption(): void {
  caption.textContent = targeting
    ? `Aiming ${targeting.spell.name}: click or Enter to cast · Tab next target · Esc cancel`
    : hoverText;
  caption.classList.toggle("aiming", targeting !== null);
}

/** Draw the pixel-art sigil into the header and use it as the favicon. */
function drawBrand(): void {
  for (const sigil of document.querySelectorAll<HTMLCanvasElement>(".sigil, .gate-sigil")) {
    sigil.getContext("2d")!.drawImage(sigilSprite(), 0, 0);
  }
  const icon = document.createElement("canvas");
  icon.width = icon.height = 64;
  const ctx = icon.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(sigilSprite(), 0, 0, 64, 64);
  $<HTMLLinkElement>("#favicon").href = icon.toDataURL();
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

// Development helpers for demos and automated checks: `spellforgeDev("clear_level")`,
// `spellforgeDev("descend")` or `spellforgeDev("give_shard")` in the browser console.
// The server ignores them unless started with SPELLFORGE_DEV_TOOLS=1.
declare global {
  interface Window {
    spellforgeDev: (command: DevCommand) => void;
  }
}
window.spellforgeDev = (command) => {
  connection.send({ type: "dev", command });
};
