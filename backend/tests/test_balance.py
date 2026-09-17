"""Balance is measured, not just judged: the probe arena and the rebalance loop."""

import asyncio
import re

import pytest
from pydantic import ValidationError
from test_api_expressiveness import SHEEP_SPELL
from test_forge import REQUEST, ScriptedWriter
from test_team import FakeCoder, FakeDesigner, run, usage

from spellforge.agents.budget import spell_limits
from spellforge.agents.forge import forge_spell
from spellforge.agents.specs import Effect, SpellReview, SpellSpec
from spellforge.agents.team import TeamForge
from spellforge.agents.verify import probe_spell, verify_spell_source
from spellforge.engine import load_plugin
from spellforge.plugins import builtin_source

# The two spells a playtester forged that made the game trivial, written by hand.
CATACLYSM = """
def on_cast(ctx, caster, target):
    for enemy in ctx.entities(faction="enemy"):
        ctx.damage(enemy.id, 4, source=caster)

define_spell(id="cataclysm", name="Cataclysm", description="4 damage to every enemy.",
             mana_cost=6, cooldown=3, target="self", on_cast=on_cast)
"""

FULL_RESTORE = """
def on_cast(ctx, caster, target):
    me = ctx.entity(caster)
    ctx.heal(caster, me.max_hp - me.hp)

define_spell(id="full_restore", name="Full Restore", description="Heal to full HP.",
             mana_cost=8, cooldown=5, target="self", on_cast=on_cast)
"""


def mend(amount: int) -> str:
    return f"""
def on_cast(ctx, caster, target):
    ctx.heal(caster, {amount})

define_spell(id="mend", name="Mend", description="Heals you.", mana_cost=8, cooldown=5,
             target="self", on_cast=on_cast)
"""


def measure(source: str):
    plugin = load_plugin("probe_test", source)
    spell = plugin.spells[0]
    measurement = probe_spell(plugin)
    return measurement, measurement.problems(
        spell_limits(spell.mana_cost, spell.cooldown, spell.range), spell.mana_cost, spell.cooldown
    )


def renamed(source: str) -> str:
    for old in set(re.findall(r'id="([a-z_]+)"', source)):
        source = source.replace(f'"{old}"', f'"{old}_copy"')
    return source


@pytest.mark.parametrize("name", ["firebolt", "frost_nova"])
def test_builtin_spells_are_within_budget(name):
    _, problems = measure(renamed(builtin_source(name)))
    assert problems == []


def test_explosive_sheep_is_within_budget():
    measurement, problems = measure(SHEEP_SPELL)
    assert problems == [] and measurement.control == 3


def test_level_wide_damage_is_rejected_for_its_reach():
    measurement, problems = measure(CATACLYSM)
    assert measurement.farthest_reach == 19
    assert "not the whole level" in problems[0]


def test_heal_to_full_is_rejected_for_its_size():
    measurement, problems = measure(FULL_RESTORE)
    assert measurement.healing == 18
    assert problems == [
        "balance probe: one cast healed 18 HP (starting from 2 HP); the limit for 8 mana, "
        "cooldown 5 is 14.5"
    ]


def test_verification_reports_balance_problems_separately():
    report = verify_spell_source("forged_9", CATACLYSM, {})
    assert not report.ok
    assert report.balance_problems and set(report.balance_problems) <= set(report.problems)


def test_specs_need_absolute_amounts():
    with pytest.raises(ValidationError, match="absolute amount"):
        Effect(kind="heal", summary="Heal to full", amount=0, duration=0, radius=0, max_targets=1)


def test_single_writer_gets_balance_problems_as_feedback():
    writer = ScriptedWriter(FULL_RESTORE, mend(12))
    outcome = asyncio.run(forge_spell(REQUEST, writer, "forged_1"))
    assert outcome.ok
    assert any("healed 18 HP" in p for p in outcome.attempts[0].problems)


MEND_SPEC = SpellSpec(
    name="Mend",
    description="Heals you for 18 HP.",
    target="self",
    range=0,
    mana_cost=8,
    cooldown=5,
    effects=[
        Effect(kind="heal", summary="Heal 18 HP", amount=18, duration=0, radius=0, max_targets=1)
    ],
    needs_sprite=False,
    sprite_description="",
    edge_cases=[],
)


class ProbeAwareBalancer:
    """Approves at first; when shown probe measurements, cuts the heal to 12."""

    def __init__(self):
        self.measurements = []

    async def review_spell(self, spec, known_spells, on_progress=None, measurements=None):
        if not measurements:
            review = SpellReview(
                verdict="approve", rationale="Fine.", exploits_considered=[], changes=[], spec=spec
            )
            return review, usage()
        self.measurements.append(measurements)
        smaller = spec.model_copy(
            update={
                "description": "Heals you for 12 HP.",
                "effects": [
                    spec.effects[0].model_copy(update={"amount": 12, "summary": "Heal 12 HP"})
                ],
            }
        )
        review = SpellReview(
            verdict="adjust",
            rationale="Measured too strong.",
            exploits_considered=[],
            changes=[],
            spec=smaller,
        )
        return review, usage()


def test_spell_measured_over_budget_goes_back_to_the_balancer():
    balancer = ProbeAwareBalancer()
    coder = FakeCoder(mend(18), mend(12))
    team = TeamForge(FakeDesigner(MEND_SPEC), balancer, coder, speculative=False)
    outcome, events = run(team)
    assert outcome.ok, outcome.verification.problems
    [shown] = balancer.measurements
    assert "healed 18 HP" in shown[0]
    assert outcome.team["rebalance"] == shown
    assert '"amount": 12' in coder.tasks[-1][0]
    assert any("back to the Balancer" in message for _, message, _ in events)
