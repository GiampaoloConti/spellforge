"""Same seed + same inputs => identical games. Agents' simulations and replays rely on this."""

import json
import random

import pytest

from spellforge.engine import DIRECTIONS, Cast, EventType, Game, InvalidAction, Move, Wait
from spellforge.plugins import builtin_encounters, default_registry

SPELLS = ("firebolt", "frost_nova")


def play(seed: int, script_seed: int, rounds: int = 150) -> Game:
    """Play a generated level with a scripted random player that also casts spells."""
    game = Game.new(seed, default_registry(), spells=SPELLS, encounters=builtin_encounters)
    script = random.Random(script_seed)
    for _ in range(rounds):
        if game.status.value != "playing":
            break
        enemies = [e for e in game.entities.values() if e.faction == "enemy"]
        options = [Move(script.choice(DIRECTIONS)), Wait(), Cast("frost_nova")]
        if enemies:
            options.append(Cast("firebolt", script.choice(enemies).pos))
        for action in script.sample(options, len(options)):
            try:
                game.submit(action)
                break
            except InvalidAction:
                continue
    return game


def fingerprint(game: Game) -> str:
    return json.dumps(
        {"snapshot": game.snapshot(), "history": [e.to_dict() for e in game.history]},
        sort_keys=True,
    )


def test_same_seed_and_inputs_replay_identically():
    assert fingerprint(play(seed=42, script_seed=1)) == fingerprint(play(seed=42, script_seed=1))


def test_different_seeds_produce_different_dungeons():
    maps = {tuple(Game.new(seed, default_registry()).map.to_ascii()) for seed in range(5)}
    assert len(maps) == 5


@pytest.mark.parametrize("seed", range(8))
def test_long_random_playthroughs_never_break(seed):
    game = play(seed=seed, script_seed=seed, rounds=300)
    kinds = {e.type for e in game.history}
    assert EventType.PLUGIN_DISABLED not in kinds
    assert EventType.SPELL_CAST in kinds
    player = game.player
    assert 0 <= player.hp <= player.max_hp and 0 <= player.mana <= player.max_mana
    positions = [e.pos for e in game.entities.values()]
    assert len(positions) == len(set(positions)), "two entities share a tile"
    assert all(not game.map.is_wall(p) for p in positions)
