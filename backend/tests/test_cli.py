import pytest

from spellforge.cli import parse, play, render
from spellforge.engine import Cast, Game, GameStatus, Move, Pos, Wait
from spellforge.plugins import default_registry


def small_game() -> Game:
    return Game.from_ascii(
        ["########", "#@....g#", "########"],
        default_registry(),
        {"g": "goblin"},
        spells=("firebolt", "frost_nova"),
    )


def test_parse_commands():
    game = small_game()
    assert parse("dd.", game) == [Move(Pos(1, 0)), Move(Pos(1, 0)), Wait()]
    assert parse("1 3 1", game) == [Cast("firebolt", Pos(3, 1))]
    assert parse("1", game) == [Cast("firebolt", Pos(6, 1))]  # auto-targets nearest enemy
    assert parse("2", game) == [Cast("frost_nova")]
    for bad in ("9", "1 2", "dance"):
        with pytest.raises(ValueError):
            parse(bad, game)


def test_render_shows_map_entities_and_spells():
    screen = render(small_game())
    assert "#@....g#" in screen
    assert "HP 20/20" in screen and "Firebolt" in screen and "goblin at 6,1" in screen


def test_scripted_session_clears_the_level():
    game = small_game()
    commands = iter(["?", "nonsense", "1", "1", "quit"])
    output: list[str] = []
    result = play(game, read=lambda _prompt: next(commands), write=output.append)
    assert result is GameStatus.PLAYING
    text = "\n".join(output)
    assert (
        "unknown command" in text
        and "The goblin dies!" in text
        and "You cast Firebolt." in text
        and "Stairs down have opened" in text
        and "Depth 1" in text
    )
