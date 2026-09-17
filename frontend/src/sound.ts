// Looping background music. Browsers block autoplay until the player interacts, so we
// start on the first key/click. A mute button (persisted) toggles it.

const MUTE_KEY = "spellforge.muted";

export class Soundtrack {
  private readonly audio = new Audio("/soundtrack.mp3");
  private readonly button: HTMLButtonElement;
  private started = false;

  constructor(button: HTMLButtonElement) {
    this.button = button;
    this.audio.loop = true;
    this.audio.volume = 0.35;
    this.render();
    button.addEventListener("click", () => this.toggleMute());
    // The first gesture anywhere unlocks audio; once is enough.
    const unlock = () => this.start();
    window.addEventListener("keydown", unlock, { once: true });
    window.addEventListener("pointerdown", unlock, { once: true });
  }

  private start(): void {
    this.started = true;
    if (!this.muted) void this.audio.play().catch(() => {});
  }

  private get muted(): boolean {
    try {
      return localStorage.getItem(MUTE_KEY) === "1";
    } catch {
      return false;
    }
  }

  private toggleMute(): void {
    const next = !this.muted;
    try {
      localStorage.setItem(MUTE_KEY, next ? "1" : "0");
    } catch {
      // storage unavailable: mute lasts for this page only
    }
    if (next) this.audio.pause();
    else if (this.started) void this.audio.play().catch(() => {});
    this.render();
  }

  private render(): void {
    this.button.textContent = this.muted ? "🔇" : "🔊";
    this.button.setAttribute("aria-label", this.muted ? "Unmute music" : "Mute music");
    this.button.setAttribute("aria-pressed", String(this.muted));
  }
}
