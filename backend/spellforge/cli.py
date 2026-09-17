"""A minimal terminal client: renders the game as ASCII and reads line commands.

This is a thin client on purpose, like the browser client will be: it only turns text
into `Action`s and events into text. All rules live in the engine.
"""

from __future__ import annotations

import argparse
import random
from collections.abc import Callable

from spellforge.engine import (
    Action,
    Cast,
    Game,
    GameStatus,
    InvalidAction,
    Move,
    Pos,
    Wait,
)
from spellforge.engine.api import Target
from spellforge.narration import Narrator
from spellforge.plugins import default_registry

MOVES = {
    "w": Pos(0, -1),
    "s": Pos(0, 1),
    "a": Pos(-1, 0),
    "d": Pos(1, 0),
    "q": Pos(-1, -1),
    "e": Pos(1, -1),
    "z": Pos(-1, 1),
    "c": Pos(1, 1),
}

SIGHT_RANGE = 10

HELP = """\
Commands (press Enter after each line):
  w a s d / q e z c   move (diagonals on q e z c); walk into an enemy to attack.
                      Several at once works too: "ddd"
  .                   wait a turn
  <n>                 cast spell n at the nearest visible enemy (or yourself)
  <n> <x> <y>         cast spell n at tile x,y
  ?                   this help
  quit                leave"""


def render(game: Game) -> str:
    grid = [list(row) for row in game.map.to_ascii()]
    for entity in game.entities.values():
        grid[entity.pos.y][entity.pos.x] = entity.glyph
    width = game.map.width
    lines = [
        "    " + "".join(str(x // 10) if x % 10 == 0 else " " for x in range(width)),
        "    " + "".join(str(x % 10) for x in range(width)),
    ]
    lines += [f"{y:>3} " + "".join(row) for y, row in enumerate(grid)]

    p = game.player
    statuses = ", ".join(f"{s} ({i.remaining or 'permanent'})" for s, i in p.statuses.items())
    lines.append(
        f"Turn {game.turn}   HP {p.hp}/{p.max_hp}   Mana {p.mana}/{p.max_mana}"
        + (f"   [{statuses}]" if statuses else "")
    )
    for n, spell in enumerate(game.snapshot()["spells"], start=1):
        state = (
            "DISABLED"
            if spell["disabled"]
            else f"cooldown {spell['cooldown_remaining']}"
            if spell["cooldown_remaining"]
            else "ready"
        )
        target = spell["target"] if spell["target"] == "self" else f"range {spell['range']}"
        lines.append(f"  {n}. {spell['name']} ({spell['mana_cost']} mana, {target}): {state}")
    for e in game.entities.values():
        near = e.pos.distance_to(p.pos) <= SIGHT_RANGE
        if e is not p and near and game.map.has_line_of_sight(p.pos, e.pos):
            extra = f" [{', '.join(e.statuses)}]" if e.statuses else ""
            lines.append(
                f"  {e.glyph} {e.name} at {e.pos.x},{e.pos.y}  HP {e.hp}/{e.max_hp}{extra}"
            )
    return "\n".join(lines)


def parse(line: str, game: Game) -> list[Action]:
    """Turn one input line into actions. Raises ValueError with a message for bad input."""
    words = line.split()
    if not words:
        return []
    if words[0].isdigit():
        index = int(words[0]) - 1
        if not 0 <= index < len(game.spellbook):
            raise ValueError("no spell with that number")
        spell = game.registry.spells[game.spellbook[index]]
        if len(words) == 3:
            return [Cast(spell.id, Pos(int(words[1]), int(words[2])))]
        if len(words) != 1:
            raise ValueError("usage: <n> or <n> <x> <y>")
        if spell.target is Target.SELF:
            return [Cast(spell.id)]
        target = game.ctx.nearest_hostile(game.player.id, spell.range)
        if target is None:
            raise ValueError("no visible enemy in range; give a target: <n> <x> <y>")
        return [Cast(spell.id, target.pos)]
    if len(words) == 1 and all(ch in MOVES or ch == "." for ch in words[0]):
        return [Wait() if ch == "." else Move(MOVES[ch]) for ch in words[0]]
    raise ValueError("unknown command, type ? for help")


def play(
    game: Game,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> GameStatus:
    narrator = Narrator(game)
    write(HELP)
    while game.status is GameStatus.PLAYING:
        write("\n" + render(game))
        try:
            line = read("> ").strip().lower()
        except EOFError:
            break
        if line in ("quit", "exit"):
            break
        if line == "?":
            write(HELP)
            continue
        try:
            actions = parse(line, game)
        except ValueError as exc:
            write(str(exc))
            continue
        for action in actions:
            try:
                events = game.submit(action)
            except InvalidAction as exc:
                write(f"Can't: {exc}")
                break
            for text in narrator.narrate(events):
                write(text)
            if game.status is not GameStatus.PLAYING:
                break
    return game.status


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="spellforge", description="Play Spellforge in a terminal."
    )
    parser.add_argument("--seed", type=int, default=None, help="dungeon seed (random if omitted)")
    args = parser.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    print(f"Spellforge, seed {seed}")
    game = Game.new(seed, default_registry(), spells=("firebolt", "frost_nova"))
    play(game)
