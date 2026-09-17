"""The Dungeon Master: player profiles and the counter-monster pipeline (scripted agents)."""

import asyncio

from test_team import FakeArtist, FakeCoder, usage

from spellforge.agents.dungeon_master import DungeonMaster, profile_player
from spellforge.agents.specs import Effect, MonsterReview, MonsterSpec
from spellforge.engine import Cast, Game, Move, Pos, Wait
from spellforge.plugins import default_registry

WARDEN = MonsterSpec(
    name="Warded Golem",
    description="A stone golem wrapped in a ward that drinks spell damage.",
    counters="You win fights with Firebolt from range; its ward heals it when hit from afar.",
    weakness="The ward does nothing against melee.",
    glyph="W",
    max_hp=14,
    attack=3,
    behaviour="Walks toward the nearest hostile and attacks when adjacent.",
    abilities=[
        Effect(
            kind="heal",
            summary="Heals half of the damage taken from range",
            amount=0,
            duration=0,
            radius=0,
            max_targets=1,
        )
    ],
    sprite_description="a hulking grey golem with a glowing blue rune",
    taunt="Your fire will only feed it.",
)

GOLEM = """
def ward(ctx, status, amount, source):
    me = ctx.entity(status.holder)
    attacker = ctx.entity(source) if source is not None else None
    if me is not None and attacker is not None and me.pos.distance_to(attacker.pos) > 1:
        ctx.heal(status.holder, amount // 2)


def act(ctx, me):
    if not ctx.has_status(me, "golem_ward"):
        ctx.apply_status(me, "golem_ward", None)
    body = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=8)
    if target is None:
        return
    if body.pos.distance_to(target.pos) == 1:
        ctx.attack(me, target.id)
    else:
        ctx.step_toward(me, target.pos)


define_status(id="golem_ward", name="Ward", description="Heals from ranged hits.",
              on_damaged=ward)
define_monster(id="warded_golem", name="warded golem", description="Drinks spells.",
               glyph="W", max_hp=14, attack=3, act=act, sprite="dm_1_art")
"""

TAKEN = {"spells": [], "statuses": [], "monsters": [], "sprites": []}


class FakeDMAgent:
    async def design_counter(self, profile, depth, existing, on_progress=None):
        return WARDEN, usage()


class FakeMonsterBalancer:
    def __init__(self, verdict="approve"):
        self.verdict = verdict

    async def review_monster(self, spec, depth, on_progress=None):
        review = MonsterReview(
            verdict=self.verdict, rationale="Fair.", exploits_considered=[], changes=[], spec=spec
        )
        return review, usage()


def run(dm):
    events = []

    async def progress(stage, message, **details):
        events.append((stage, message, details))

    outcome = asyncio.run(dm.create_counter("profile", 2, ["goblin"], TAKEN, "dm_1", progress))
    return outcome, events


def test_counter_monster_pipeline_produces_a_tested_monster_with_art():
    coder = FakeCoder(GOLEM)
    dm = DungeonMaster(FakeDMAgent(), FakeMonsterBalancer(), coder, FakeArtist())
    outcome, events = run(dm)
    assert outcome.ok, outcome.verification.problems if outcome.verification else outcome.error
    assert outcome.monster_id == "warded_golem"
    assert outcome.verification.monster.sprite == "dm_1_art"
    assert "Do not call define_sprite" in coder.tasks[0][0]
    assert set(outcome.agents) == {"dungeon_master", "balancer", "coder", "artist"}
    done = [stage for stage, _, details in events if details.get("done")]
    assert done == ["designing", "balancing", "drawing", "testing"]


def test_monster_that_breaks_its_spec_is_sent_back():
    weaker = GOLEM.replace("max_hp=14", "max_hp=9")
    coder = FakeCoder(weaker, GOLEM)
    outcome, _ = run(DungeonMaster(FakeDMAgent(), FakeMonsterBalancer(), coder, FakeArtist()))
    assert outcome.ok
    assert "spec says max_hp 14, plugin has 9" in outcome.attempts[0].problems


def test_rejected_monster_is_not_built():
    coder = FakeCoder(GOLEM)
    dm = DungeonMaster(FakeDMAgent(), FakeMonsterBalancer("reject"), coder, FakeArtist())
    outcome, _ = run(dm)
    assert not outcome.ok and coder.tasks == []


def test_profile_describes_how_the_player_fights():
    game = Game.from_ascii(
        ["##########", "#@.g....g#", "##########"],
        default_registry(),
        {"g": "goblin"},
        spells=("firebolt", "frost_nova"),
    )
    names = {e.id: e.name for e in game.entities.values()}
    game.entities[2].hp = 20  # sturdy enough to survive and hit back
    game.submit(Cast("firebolt", Pos(3, 1)))
    goblin = game.entities[2]
    if goblin.pos.distance_to(game.player.pos) > 1:
        game.submit(Move(Pos(1, 0)))
    game.submit(Move(game.player.pos.direction_to(goblin.pos)))
    game.submit(Wait())
    profile = profile_player(game, names)
    assert "Firebolt x1" in profile
    assert "Melee attacks: 1" in profile
    assert "5 with spells" in profile and "3 in melee" in profile
    assert "Damage taken from: goblin" in profile
