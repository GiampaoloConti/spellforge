// The invite-code screen, shown when the server answers a connection with "locked".
//
// A code that worked is remembered in localStorage, so friends type it once. Storage can be
// unavailable (private windows, blocked site data), so every access is wrapped in try/catch
// and the gate simply asks again.

const STORAGE_KEY = "spellforge.inviteCode";

function stored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function store(code: string | null): void {
  try {
    if (code === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Not remembered; the player types it again next time.
  }
}

export class InviteGate {
  private readonly root: HTMLElement;
  private readonly form: HTMLFormElement;
  private readonly input: HTMLInputElement;
  private readonly error: HTMLElement;
  private readonly submit: HTMLButtonElement;
  private triedStored = false;
  private pending: string | null = null; // the code sent last, remembered once accepted
  private readonly unlock: (code: string) => void;

  /** `unlock` sends the code to the server. */
  constructor(root: HTMLElement, unlock: (code: string) => void) {
    this.root = root;
    this.unlock = unlock;
    this.form = root.querySelector("form")!;
    this.input = root.querySelector("input")!;
    this.error = root.querySelector(".gate-error")!;
    this.submit = root.querySelector("button")!;
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      const code = this.input.value.trim();
      if (code) this.send(code);
    });
  }

  /** A new connection: the stored code may be tried again. */
  reset(): void {
    this.triedStored = false;
  }

  /** The server wants a code. `error` says why the previous one was refused. */
  locked(error: string | null): void {
    const remembered = stored();
    if (error === null && remembered && !this.triedStored) {
      this.triedStored = true;
      this.send(remembered);
      return;
    }
    if (error !== null && this.pending === remembered) store(null); // it stopped working
    this.root.hidden = false;
    this.submit.disabled = false;
    this.error.textContent = error ?? "";
    this.input.focus();
  }

  /** The server let us in. */
  unlocked(): void {
    if (this.pending !== null) store(this.pending);
    this.root.hidden = true;
  }

  private send(code: string): void {
    this.pending = code;
    this.submit.disabled = true;
    this.unlock(code);
  }
}
