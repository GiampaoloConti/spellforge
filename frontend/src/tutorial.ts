// First-run tutorial: a dismissible card explaining what each part of the UI does.
// Shown only to players this browser hasn't seen before (see main.ts).

const ITEMS: [string, string][] = [
  ["The dungeon", "Move with WASD, the arrows or QEZC. Walk into a monster to attack it. Clear a level to open the stairs down."],
  ["Minimap (top-right)", "The level at a glance — you are the purple dot, the stairs down are gold once they open."],
  ["Stats & spells (bottom-left)", "Your HP, mana and arcane shards, with your spellbook below. Press 1–9 to cast a spell, then aim with the mouse or keys."],
  ["Arcane Forge (right)", "Spend an arcane shard — hidden every third level — to describe ANY spell you like. A team of AI agents designs, balances, writes and tests it while you keep playing."],
  ["Dungeon Master (right)", "Every couple of levels it studies how you fight and unleashes a new monster built to counter you."],
  ["Log", "A running account of everything that just happened."],
];

export class Tutorial {
  show(): Promise<void> {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal";
      const card = document.createElement("div");
      card.className = "modal-card tutorial-card";

      const heading = document.createElement("h2");
      heading.textContent = "Welcome to Spellforge";
      const intro = document.createElement("p");
      intro.className = "muted";
      intro.textContent =
        "A roguelike where the spells and monsters are invented on the fly by AI. A quick tour:";

      const list = document.createElement("dl");
      list.className = "tutorial-list";
      for (const [term, description] of ITEMS) {
        const dt = document.createElement("dt");
        dt.textContent = term;
        const dd = document.createElement("dd");
        dd.textContent = description;
        list.append(dt, dd);
      }

      const button = document.createElement("button");
      button.type = "button";
      button.className = "modal-go";
      button.textContent = "Enter the dungeon";
      button.addEventListener("click", () => {
        overlay.remove();
        resolve();
      });

      card.append(heading, intro, list, button);
      overlay.append(card);
      document.body.append(overlay);
      button.focus();
    });
  }
}
