"""Can the plugin API express the kind of spell a player would invent?

The spell from the README pitch: "a spell that turns enemies into sheep, but they
explode after 3 turns", hot-loaded into a game that is already running, as agents will.
"""

import pytest
from conftest import events_of, plugin

from spellforge.engine import Cast, EventType, InvalidAction, Wait

SHEEP_SPELL = """
FUSE_TURNS = 3
BLAST_RADIUS = 1
BLAST_DAMAGE = 4


def on_cast(ctx, caster, target):
    victim = ctx.entity_at(target)
    if victim.is_player:
        ctx.log("You feel briefly woolly.")
        return
    ctx.apply_status(victim.id, "sheep_bomb", FUSE_TURNS, source=caster)


def on_apply(ctx, status):
    ctx.log(f"The {ctx.entity(status.holder).name} turns into a sheep. Its fuse is lit.")


def on_expire(ctx, status):
    sheep = ctx.entity(status.holder)
    ctx.log("BAAA-BOOM!")
    for other in ctx.entities_in_radius(sheep.pos, BLAST_RADIUS):
        if other.id != sheep.id:
            ctx.damage(other.id, BLAST_DAMAGE, source=status.source)
    ctx.damage(sheep.id, sheep.hp, source=status.source)


define_status(
    id="sheep_bomb",
    name="Sheep (lit fuse)",
    description="A harmless sheep for now. Explodes when the fuse runs out.",
    prevents_action=True,
    on_apply=on_apply,
    on_expire=on_expire,
)

define_spell(
    id="explosive_sheep",
    name="Explosive Sheep",
    description="Turns a creature into a sheep that explodes after 3 turns.",
    mana_cost=4,
    cooldown=3,
    target="entity",
    range=6,
    on_cast=on_cast,
)
"""


def test_hot_loaded_explosive_sheep(make_game):
    game = make_game(["##########", "#@...gg..#", "##########"])
    sheep, neighbour = game.entities[2], game.entities[3]
    game.submit(Wait())  # the game is running before the spell exists
    with pytest.raises(InvalidAction):
        game.submit(Cast("explosive_sheep", sheep.pos))

    game.load_plugin(plugin("explosive_sheep", SHEEP_SPELL))
    game.learn_spell("explosive_sheep")
    events = game.submit(Cast("explosive_sheep", sheep.pos))
    assert "sheep_bomb" in sheep.statuses

    for _ in range(2):
        events += game.submit(Wait())
    skipped = [e["entity"] for e in events_of(events, EventType.TURN_SKIPPED)]
    assert skipped.count(sheep.id) == 3
    assert not sheep.alive
    assert neighbour.hp == 6 - 4
    texts = [e["text"] for e in events_of(events, EventType.MESSAGE)]
    assert texts == ["The goblin turns into a sheep. Its fuse is lit.", "BAAA-BOOM!"]
    assert not events_of(game.history, EventType.PLUGIN_DISABLED)
