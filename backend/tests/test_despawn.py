"""ctx.despawn removes a summon cleanly (the stuck-minion bug) and refuses natural monsters."""

from conftest import events_of, plugin

from spellforge.engine import Cast, EventType, Wait
from spellforge.engine.context import GameContext
from spellforge.engine.geometry import Pos

# A summon that fades: the old failure was despawning it via ctx.damage(minion, huge),
# which tripped the damage cap, raised PluginError and disabled the plugin — leaving the
# minion stuck on the map. ctx.despawn is the clean way out.
SUMMON_SPELL = """
FADE_TURNS = 2


def on_cast(ctx, caster, target):
    minion = ctx.spawn("goblin", target, "player")
    if minion is not None:
        ctx.apply_status(minion, "fading", FADE_TURNS, source=caster)


def on_expire(ctx, status):
    ctx.despawn(status.holder)


define_status(
    id="fading",
    name="Fading",
    description="A summoned ally that fades away.",
    on_expire=on_expire,
)

define_spell(
    id="summon_ally",
    name="Summon Ally",
    description="Summons an ally that fades after a couple of turns.",
    mana_cost=3,
    cooldown=5,
    target="tile",
    range=5,
    on_cast=on_cast,
)
"""


def test_summoned_ally_despawns_cleanly_when_it_fades(make_game):
    game = make_game(["#######", "#@....#", "#######"])  # no enemies to interfere
    game.load_plugin(plugin("summon_ally", SUMMON_SPELL))
    game.learn_spell("summon_ally")

    events = game.submit(Cast("summon_ally", Pos(3, 1)))
    minion = next(e for e in game.entities.values() if e is not game.player)
    assert minion.summoned and minion.faction == "player"

    for _ in range(4):  # its status expires after a couple of its own turns
        if minion.id not in game.entities:
            break
        events += game.submit(Wait())

    assert minion.id not in game.entities and not minion.alive
    assert minion.id in {e["entity"] for e in events_of(events, EventType.DIED)}
    assert not events_of(events, EventType.PLUGIN_DISABLED)  # the plugin never errored


def test_despawn_refuses_natural_monsters_and_the_player(make_game):
    """The balance guard: a spell can't despawn (instantly delete) a real enemy or the player."""
    game = make_game(["#####", "#@g.#", "#####"])
    ctx = GameContext(game)
    enemy = next(e for e in game.entities.values() if e.faction == "enemy")

    assert ctx.despawn(enemy.id) is False
    assert enemy.alive and enemy.id in game.entities
    assert ctx.despawn(game.player.id) is False
    assert game.player.alive
