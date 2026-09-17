from conftest import events_of, plugin

from spellforge.engine import Cast, EventType, Move, Pos, Wait

STATUS_KIT = plugin(
    "status_kit",
    """
    def burn(ctx, status):
        ctx.damage(status.holder, 1, source=status.source)

    def announce(ctx, status):
        ctx.log("applied " + status.status_id)

    def expire(ctx, status):
        ctx.log("expired " + status.status_id)

    def thorns(ctx, status, amount, source):
        if source is not None:
            ctx.damage(source, 1, source=status.holder)

    define_status(id="burning", name="Burning", description="Takes 1 damage each turn.",
                  on_apply=announce, on_turn=burn, on_expire=expire)
    define_status(id="thorny", name="Thorny", description="Hurts attackers.",
                  on_damaged=thorns)
    define_status(id="ward", name="Ward", description="A lingering ward.",
                  on_apply=announce, on_expire=expire)

    def ignite(ctx, caster, target):
        ctx.apply_status(ctx.entity_at(target).id, "burning", 3, source=caster)

    def thornify(ctx, caster, target):
        ctx.apply_status(ctx.entity_at(target).id, "thorny", None, source=caster)

    def ward(ctx, caster, target):
        ctx.apply_status(caster, "ward", 2)

    def unward(ctx, caster, target):
        ctx.remove_status(caster, "ward")

    for spell_id, fn, kind in (("ignite", ignite, "entity"), ("thornify", thornify, "entity"),
                               ("ward_self", ward, "self"), ("unward", unward, "self")):
        define_spell(id=spell_id, name=spell_id, description="Test spell.", mana_cost=0,
                     target=kind, range=6, on_cast=fn)
    """,
)
SPELLS = ("ignite", "thornify", "ward_self", "unward")


def messages(game):
    return [e["text"] for e in events_of(game.history, EventType.MESSAGE)]


def test_damage_over_time_ticks_for_duration_then_expires(make_game):
    game = make_game(["#####", "#@.g#", "#####"], spells=SPELLS, plugins=(STATUS_KIT,))
    goblin = game.entities[2]
    goblin.attack = 0
    goblin_hp = []
    game.submit(Cast("ignite", Pos(3, 1)))
    goblin_hp.append(goblin.hp)
    for _ in range(3):
        game.submit(Wait())
        goblin_hp.append(goblin.hp)
    assert goblin_hp == [5, 4, 3, 3]
    assert messages(game) == ["applied burning", "expired burning"]


def test_self_applied_status_lasts_the_next_n_turns(make_game):
    game = make_game(["#####", "#@..#", "#####"], spells=SPELLS, plugins=(STATUS_KIT,))
    game.submit(Cast("ward_self"))
    assert game.player.statuses["ward"].remaining == 2
    game.submit(Wait())
    assert game.player.statuses["ward"].remaining == 1
    game.submit(Wait())
    assert "ward" not in game.player.statuses


def test_reapplying_keeps_longer_duration_without_rerunning_on_apply(make_game):
    game = make_game(["#####", "#@..#", "#####"], spells=SPELLS, plugins=(STATUS_KIT,))
    game.submit(Cast("ward_self"))
    game.submit(Wait())
    game.submit(Cast("ward_self"))
    assert game.player.statuses["ward"].remaining == 2
    assert messages(game).count("applied ward") == 1


def test_remove_status_skips_on_expire(make_game):
    game = make_game(["#####", "#@..#", "#####"], spells=SPELLS, plugins=(STATUS_KIT,))
    game.submit(Cast("ward_self"))
    events = game.submit(Cast("unward"))
    assert "ward" not in game.player.statuses
    assert events_of(events, EventType.STATUS_REMOVED) == [{"entity": 1, "status": "ward"}]
    assert "expired ward" not in messages(game)


def test_on_damaged_reacts_to_attacker(make_game):
    game = make_game(["#####", "#@g.#", "#####"], spells=SPELLS, plugins=(STATUS_KIT,))
    game.submit(Cast("thornify", Pos(2, 1)))
    hp_before = game.player.hp
    game.submit(Move(Pos(1, 0)))
    goblin_attack, thorns = 2, 1
    assert game.player.hp == hp_before - thorns - goblin_attack


def test_on_death_runs_while_entity_is_still_visible(make_game):
    volatile = plugin(
        "volatile",
        """
        def boom(ctx, status):
            me = ctx.entity(status.holder)
            ctx.log(f"{me.name} alive={me.alive} bursts")
            for other in ctx.entities_in_radius(me.pos, 1, faction="enemy"):
                ctx.damage(other.id, 10, source=status.holder)

        define_status(id="volatile", name="Volatile", description="Explodes on death.",
                      on_death=boom)

        """,
    )
    game = make_game(
        ["#########", "#@..ggg.#", "#########"], spells=("firebolt",), plugins=(volatile,)
    )
    for goblin in list(game.entities.values())[1:]:
        game.apply_status(goblin, "volatile", None, source=None)
    game.entities[2].hp = 1
    game.submit(Cast("firebolt", Pos(7, 1)))
    assert messages(game).count("goblin alive=False bursts") == 3
    assert game.stairs is not None  # every goblin died in the chain
