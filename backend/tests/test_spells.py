import pytest
from conftest import events_of, plugin

from spellforge.engine import Cast, EventType, InvalidAction, Pos, Wait

CORRIDOR = ["#########", "#@..gg..#", "#########"]


def test_firebolt_hits_first_creature_in_line(make_game):
    game = make_game(CORRIDOR, spells=("firebolt",))
    first, second = game.entities[2], game.entities[3]
    events = game.submit(Cast("firebolt", Pos(7, 1)))
    assert events_of(events, EventType.SPELL_CAST) == [
        {"caster": game.player.id, "spell": "firebolt", "target": [7, 1]}
    ]
    assert first.hp == 6 - 5
    assert second.hp == 6
    assert game.player.mana == 10 - 3 + 1


def test_firebolt_with_nothing_in_the_way(make_game):
    game = make_game(["#######", "#@....#", "#######"], spells=("firebolt",))
    events = game.submit(Cast("firebolt", Pos(5, 1)))
    assert [e["text"] for e in events_of(events, EventType.MESSAGE)] == [
        "The firebolt hits nothing."
    ]


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (Pos(0, 1), "invalid target"),
        (Pos(8, 5), "invalid target"),
        (None, "needs a target"),
    ],
)
def test_spell_target_validation(make_game, target, message):
    game = make_game(CORRIDOR, spells=("firebolt",))
    with pytest.raises(InvalidAction, match=message):
        game.submit(Cast("firebolt", target))
    assert game.player.mana == 10


def test_range_and_line_of_sight_are_enforced(make_game):
    game = make_game(
        ["############", "#@#........#", "#..........#", "############"], spells=("firebolt",)
    )
    with pytest.raises(InvalidAction, match="line of sight"):
        game.submit(Cast("firebolt", Pos(3, 1)))
    with pytest.raises(InvalidAction, match="out of range"):
        game.submit(Cast("firebolt", Pos(10, 2)))


def test_not_enough_mana(make_game):
    game = make_game(CORRIDOR, spells=("firebolt",))
    game.player.mana = 2
    with pytest.raises(InvalidAction, match="mana"):
        game.submit(Cast("firebolt", Pos(4, 1)))


def test_unlearned_spells_cannot_be_cast(make_game):
    game = make_game(CORRIDOR)  # firebolt is registered but not learned
    with pytest.raises(InvalidAction, match="don't know"):
        game.submit(Cast("firebolt", Pos(4, 1)))


def test_cooldown_counts_player_turns_between_casts(make_game):
    game = make_game(["#######", "#@....#", "#######"], spells=("frost_nova",))
    game.submit(Cast("frost_nova"))
    for remaining in (4, 3, 2, 1):
        assert game.spell_cooldown("frost_nova") == remaining
        with pytest.raises(InvalidAction, match="cooldown"):
            game.submit(Cast("frost_nova"))
        game.submit(Wait())
    assert game.spell_cooldown("frost_nova") == 0
    game.submit(Cast("frost_nova"))


def test_frost_nova_damages_and_freezes_for_exactly_two_turns(make_game):
    game = make_game(["########", "#@g...g#", "########"], spells=("frost_nova",))
    near, far = game.entities[2], game.entities[3]
    events = game.submit(Cast("frost_nova"))
    assert near.hp == 6 - 2 and far.hp == 6
    assert "frozen" in near.statuses and "frozen" not in far.statuses
    assert any("frozen solid" in e["text"] for e in events_of(events, EventType.MESSAGE))
    assert events_of(events, EventType.TURN_SKIPPED) == [{"entity": near.id}]

    events = game.submit(Wait())
    assert events_of(events, EventType.TURN_SKIPPED) == [{"entity": near.id}]
    assert events_of(events, EventType.STATUS_EXPIRED) == [{"entity": near.id, "status": "frozen"}]
    assert game.player.hp == 20

    game.submit(Wait())
    assert game.player.hp == 20 - 2


def test_entity_targeting_requires_a_creature(make_game):
    zap = plugin(
        "zap",
        """
        def on_cast(ctx, caster, target):
            ctx.damage(ctx.entity_at(target).id, 1, source=caster)

        define_spell(id="zap", name="Zap", description="Zaps a creature.", mana_cost=1,
                     target="entity", range=5, on_cast=on_cast)
        """,
    )
    game = make_game(CORRIDOR, spells=("zap",), plugins=(zap,))
    with pytest.raises(InvalidAction, match="no creature"):
        game.submit(Cast("zap", Pos(3, 1)))
    game.submit(Cast("zap", Pos(4, 1)))
    assert game.entities[2].hp == 5
