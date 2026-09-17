// The start screen: ask the player's name for the leaderboard. Resolves with the trimmed
// name (or null if they leave it blank). Prefilled for returning players.

import { MAX_NAME_LENGTH } from "./leaderboard";

export class Intro {
  ask(current: string | null): Promise<string | null> {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal";
      const form = document.createElement("form");
      form.className = "modal-card intro-card";

      const heading = document.createElement("h2");
      heading.textContent = "Enter the dungeon";
      const hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent = "Choose a name for the leaderboard.";

      const input = document.createElement("input");
      input.maxLength = MAX_NAME_LENGTH;
      input.placeholder = "Your name";
      input.value = current ?? "";
      input.setAttribute("aria-label", "Your name");

      const button = document.createElement("button");
      button.type = "submit";
      button.className = "modal-go";
      button.textContent = "Begin";

      form.append(heading, hint, input, button);
      overlay.append(form);
      document.body.append(overlay);
      input.focus();
      input.select();

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        overlay.remove();
        resolve(input.value.trim() || null);
      });
    });
  }
}
