"""A broken plugin must never crash the game: it gets disabled and play continues."""

import pytest
from conftest import events_of, plugin

from spellforge.engine import Cast, EventType, InvalidAction, Pos, Wait
from spellforge.engine.game import MAX_HOOK_DEPTH


def spell_plugin(plugin_id: str, body: str, target: str = "self"):
    """A one-spell plugin whose on_cast body is `body` (indented by 4 spaces)."""
    source = (
        "def on_cast(ctx, caster, target):\n"
        + body
        + f"\n\ndefine_spell(id='{plugin_id}', name='{plugin_id}', description='Test.',"
        + f" mana_cost=1, target='{target}', range=6, on_cast=on_cast)\n"
    )
    return plugin(plugin_id, source)


def disabled(events):
    return {e["plugin"]: e["reason"] for e in events_of(events, EventType.PLUGIN_DISABLED)}


ROOM = ["#######", "#@..g.#", "#######"]


def test_exception_in_spell_disables_plugin_and_game_continues(make_game):
    bad = spell_plugin("oops", "    ctx.log('about to fail')\n    return 1 / 0")
    game = make_game(ROOM, spells=("oops", "firebolt"), plugins=(bad,))
    events = game.submit(Cast("oops"))
    assert disabled(events) == {"oops": "ZeroDivisionError: division by zero"}
    assert game.turn == 2  # the round still completed
    assert game.snapshot()["spells"][0]["disabled"] is True
    with pytest.raises(InvalidAction, match="disabled"):
        game.submit(Cast("oops"))
    game.submit(Cast("firebolt", Pos(4, 1)))  # other plugins unaffected
    assert set(disabled(game.history)) == {"oops"}


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("    ctx.damage('goblin', 5)", "entity id must be an int"),
        ("    ctx.apply_status(caster, 'no_such_status', 2)", "unknown status"),
        ("    ctx.apply_status(caster, 'frozen', None)", "needs a duration"),
        ("    ctx.spawn('dragon', target)", "unknown monster"),
        ("    ctx.entities(faction='monsters')", "faction must be one of"),
        ("    ctx.random_int(5, 1)", "greater than high"),
        ("    ctx.damage(caster, float('nan'))", "must be finite"),
    ],
)
def test_api_misuse_disables_plugin_with_actionable_reason(make_game, body, reason):
    bad = spell_plugin("misuse", body)
    game = make_game(ROOM, spells=("misuse",), plugins=(bad,))
    events = game.submit(Cast("misuse"))
    assert reason in disabled(events)["misuse"]


def test_runaway_plugin_is_stopped_by_action_budget(make_game):
    bad = spell_plugin("spam", "    while True:\n        ctx.turn_number()")
    game = make_game(ROOM, spells=("spam",), plugins=(bad,))
    events = game.submit(Cast("spam"))
    assert "BudgetExceeded" in disabled(events)["spam"]
    game.submit(Wait())  # budget resets; game keeps going


def test_swallowed_budget_error_is_still_caught(make_game):
    body = (
        "    for i in range(5000):\n"
        "        try:\n"
        "            ctx.turn_number()\n"
        "        except:\n"
        "            pass"
    )
    bad = spell_plugin("sneaky", body)
    game = make_game(ROOM, spells=("sneaky",), plugins=(bad,))
    assert "sneaky" in disabled(game.submit(Cast("sneaky")))


def test_budget_blame_goes_to_the_runaway_hook_not_the_innocent_caller(make_game):
    cursed = plugin(
        "cursed",
        """
        def on_damaged(ctx, status, amount, source):
            while True:
                ctx.turn_number()

        def curse(ctx, caster, target):
            ctx.apply_status(ctx.entity_at(target).id, "cursed", None)

        define_status(id="cursed", name="Cursed", description="Bad news.", on_damaged=on_damaged)
        define_spell(id="curse", name="Curse", description="Curses.", mana_cost=0,
                     target="entity", range=6, on_cast=curse)
        """,
    )
    game = make_game(ROOM, spells=("curse", "firebolt"), plugins=(cursed,))
    game.submit(Cast("curse", Pos(4, 1)))
    goblin = next(e for e in game.entities.values() if e.kind == "goblin")
    events = game.submit(Cast("firebolt", goblin.pos))
    assert set(disabled(events)) == {"cursed"}
    assert "cursed" not in goblin.statuses  # the disabled plugin's statuses are cleaned up


def test_broken_monster_ai_leaves_monster_idle(make_game):
    brute = plugin(
        "brute",
        """
        def act(ctx, me):
            ctx.attack(me, None)

        define_monster(id="brute", name="brute", description="Broken.", glyph="B",
                       max_hp=5, attack=3, act=act)
        """,
    )
    game = make_game(["######", "#@b..#", "######"], legend={"b": "brute"}, plugins=(brute,))
    events = game.submit(Wait())
    assert "brute" in disabled(events)
    for _ in range(3):
        game.submit(Wait())
    assert game.player.hp == 20
    assert len(disabled(game.history)) == 1


def test_infinite_reaction_chain_fizzles_at_depth_limit(make_game):
    mirror = plugin(
        "mirror",
        """
        def reflect(ctx, status, amount, source):
            if source is not None:
                ctx.damage(source, 1, source=status.holder)

        define_status(id="mirror", name="Mirror", description="Reflects damage.",
                      on_damaged=reflect)
        define_monster(id="dummy", name="dummy", description="Hits back.", glyph="d",
                       max_hp=100, attack=0)

        def duel(ctx, caster, target):
            for e in ctx.entities():
                ctx.apply_status(e.id, "mirror", None)
            ctx.damage(ctx.entity_at(target).id, 1, source=caster)

        define_spell(id="duel", name="Duel", description="Mirror duel.", mana_cost=0,
                     target="entity", range=3, on_cast=duel)
        """,
    )
    game = make_game(
        ["#####", "#@d.#", "#####"], legend={"d": "dummy"}, spells=("duel",), plugins=(mirror,)
    )
    events = game.submit(Cast("duel", Pos(2, 1)))
    assert not disabled(events)
    assert any("fizzles" in e["text"] for e in events_of(events, EventType.MESSAGE))
    total = sum(e["amount"] for e in events_of(events, EventType.DAMAGED))
    assert total == MAX_HOOK_DEPTH
