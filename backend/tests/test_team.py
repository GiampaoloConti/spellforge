"""The agent team's orchestration, with scripted agents and the real Tester/sandbox."""

import asyncio

import pytest
from test_forge import GOOD, REQUEST

from spellforge.agents.llm import AgentError, Usage
from spellforge.agents.specs import Change, Effect, SpellReview, SpellSpec, output_schema
from spellforge.agents.spell_writer import SpellDraft, SpellRequest
from spellforge.agents.team import TeamForge

SPEC = SpellSpec(
    name="Spark",
    description="A small zap that deals 3 damage.",
    target="tile",
    range=6,
    mana_cost=2,
    cooldown=0,
    effects=[
        Effect(
            kind="damage",
            summary="3 damage to one creature",
            amount=3,
            duration=0,
            radius=0,
            max_targets=1,
        )
    ],
    needs_sprite=False,
    sprite_description="",
    edge_cases=["the tile is empty"],
)


def usage(model="claude-opus-5", seconds=1.0):
    return Usage(model=model, input_tokens=1000, output_tokens=100, seconds=seconds)


class FakeDesigner:
    def __init__(self, spec=SPEC):
        self.spec = spec

    async def design(self, request, on_progress=None):
        return self.spec, usage()


class FakeBalancer:
    def __init__(self, verdict="approve", spec=SPEC, delay=0.0):
        self.verdict, self.spec, self.delay = verdict, spec, delay

    async def review_spell(self, spec, known_spells, on_progress=None, measurements=None):
        await asyncio.sleep(self.delay)
        changes = []
        if self.verdict == "adjust":
            changes = [Change(field="mana_cost", before="2", after="3", reason="too cheap")]
        review = SpellReview(
            verdict=self.verdict,
            rationale="Checked.",
            exploits_considered=["spam"],
            changes=changes,
            spec=self.spec if self.verdict != "approve" else spec,
        )
        return review, usage()


class FakeCoder:
    """Returns scripted sources; records each task and whether it was cancelled."""

    def __init__(self, *sources, delay=0.0):
        self.sources = list(sources)
        self.delay = delay
        self.tasks: list[tuple[str, int]] = []
        self.cancelled = 0

    async def write(self, task, previous, on_progress=None):
        self.tasks.append((task, len(previous)))
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        source = self.sources.pop(0)
        if isinstance(source, Exception):
            raise source
        return SpellDraft(spell_id="spark", notes="", source=source, usage=usage())


def run(team, request=REQUEST):
    events = []

    async def progress(stage, message, **details):
        events.append((stage, message, details))

    outcome = asyncio.run(team.forge(request, "forged_1", progress))
    return outcome, events


def test_approved_design_keeps_the_speculative_draft():
    coder = FakeCoder(GOOD, delay=0.05)
    outcome, events = run(TeamForge(FakeDesigner(), FakeBalancer("approve"), coder))
    assert outcome.ok, outcome.verification.problems
    assert outcome.team["speculation"] == "used"
    assert len(coder.tasks) == 1 and coder.cancelled == 0
    assert '"mana_cost": 2' in coder.tasks[0][0]
    stages = [stage for stage, _, _ in events]
    # The Coder was already working before the Balancer finished.
    assert stages.index("coding") < max(i for i, s in enumerate(stages) if s == "balancing")
    assert outcome.team["review"]["verdict"] == "approve"
    assert set(outcome.team["agents"]) == {"designer", "balancer", "coder"}
    assert outcome.usage.input_tokens == 3000


def test_adjusted_numbers_restart_the_coder_from_the_approved_spec():
    adjusted = SPEC.model_copy(update={"mana_cost": 3})
    coder = FakeCoder(
        GOOD.replace("mana_cost=2", "mana_cost=3"),
        GOOD.replace("mana_cost=2", "mana_cost=3"),
        delay=0.2,
    )
    outcome, events = run(TeamForge(FakeDesigner(), FakeBalancer("adjust", adjusted), coder))
    assert outcome.ok, outcome.verification.problems
    assert outcome.team["speculation"] == "discarded"
    assert coder.cancelled == 1
    assert '"mana_cost": 3' in coder.tasks[-1][0]
    assert outcome.team["review"]["changes"][0]["after"] == "3"
    balancer_done = [d for s, _, d in events if s == "balancing" and d.get("done")]
    assert balancer_done[0]["verdict"] == "adjust"


def test_rejection_stops_the_pipeline():
    coder = FakeCoder(GOOD, delay=0.2)
    outcome, _ = run(TeamForge(FakeDesigner(), FakeBalancer("reject"), coder))
    assert not outcome.ok
    assert outcome.error == "the Balancer rejected it: Checked."
    assert coder.cancelled == 1


def test_tester_catches_a_coder_that_rebalanced_the_spell():
    cheaper = GOOD.replace("mana_cost=2", "mana_cost=1")
    stronger = GOOD.replace("ctx.damage(victim.id, 3,", "ctx.damage(victim.id, 6,")
    coder = FakeCoder(cheaper, stronger, GOOD)
    team = TeamForge(FakeDesigner(), FakeBalancer(), coder, max_code_attempts=3, speculative=False)
    outcome, events = run(team)
    assert outcome.ok
    first, second = outcome.attempts
    assert "spec says mana_cost 2, but define_spell declares 1" in first.problems
    assert any("dealt 6 damage" in p and "at most 3" in p for p in second.problems)
    assert [previous for _, previous in coder.tasks] == [0, 1, 2]
    assert sum(1 for stage, _, _ in events if stage == "retrying") == 2


def test_transformation_ideas_always_need_a_sprite():
    request = SpellRequest(
        idea="turn enemies into sparks", taken_ids=REQUEST.taken_ids, known_spells=[]
    )
    team = TeamForge(FakeDesigner(), FakeBalancer(), FakeCoder(GOOD), max_code_attempts=1)
    outcome, _ = run(team, request)
    assert not outcome.ok
    assert any("spec needs a sprite" in p for p in outcome.attempts[0].problems)


def test_failed_speculative_draft_falls_back_to_a_fresh_one():
    coder = FakeCoder(AgentError("boom"), GOOD)
    outcome, _ = run(TeamForge(FakeDesigner(), FakeBalancer(), coder))
    assert outcome.ok
    assert outcome.team["speculation"] == "failed"


def test_agent_errors_end_the_forge_cleanly():
    class BrokenDesigner:
        async def design(self, request, on_progress=None):
            raise AgentError("the Designer declined this request")

    outcome, _ = run(TeamForge(BrokenDesigner(), FakeBalancer(), FakeCoder(GOOD)))
    assert not outcome.ok and outcome.error == "the Designer declined this request"


@pytest.mark.parametrize("model", [SpellSpec, SpellReview])
def test_output_schemas_are_strict(model):
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        if node.get("type") == "array":
            walk(node["items"])
        assert "$ref" not in node and "minimum" not in node

    walk(output_schema(model))


# ---- the Artist ------------------------------------------------------------------------

ROCK_ART = {"k": "#140d1c", "r": "#8a8f99"}


class FakeArtist:
    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail = delay, fail
        self.calls: list[tuple[str, str]] = []

    async def draw(self, sprite_id, description, on_progress=None):
        from spellforge.agents.artist import sprite_source

        self.calls.append((sprite_id, description))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise AgentError("the Artist's sprite was unusable")
        rows = ["." * 16] * 8 + ["....kkkkkkkk...."] + ["...krrrrrrrrk..."] * 6 + ["." * 16]
        return sprite_source(sprite_id, ROCK_ART, rows), usage()


def test_artist_draws_in_parallel_and_its_sprite_is_attached():
    spec = SPEC.model_copy(update={"needs_sprite": True, "sprite_description": "a grey rock"})
    artist = FakeArtist(delay=0.05)
    coder = FakeCoder(GOOD)
    team = TeamForge(FakeDesigner(spec), FakeBalancer(), coder, artist)
    outcome, events = run(team)
    assert outcome.ok, outcome.verification.problems
    assert artist.calls == [("forged_1_art", "a grey rock")]
    assert "Do not call define_sprite" in coder.tasks[0][0]
    assert "forged_1_art" in coder.tasks[0][0]
    assert "# ---- art (drawn by the Artist) ----" in outcome.draft.source
    assert outcome.verification.sprite_count == 1
    stages = [stage for stage, _, _ in events]
    assert stages.index("drawing") < stages.index("balancing")
    assert "artist" in outcome.team["agents"]


def test_no_artist_call_when_no_sprite_is_needed():
    artist = FakeArtist()
    outcome, _ = run(TeamForge(FakeDesigner(), FakeBalancer(), FakeCoder(GOOD), artist))
    assert outcome.ok and artist.calls == []
    assert "art (drawn by the Artist)" not in outcome.draft.source


def test_artist_failure_ends_the_forge_cleanly():
    spec = SPEC.model_copy(update={"needs_sprite": True, "sprite_description": "a rock"})
    team = TeamForge(FakeDesigner(spec), FakeBalancer(), FakeCoder(GOOD), FakeArtist(fail=True))
    outcome, _ = run(team)
    assert not outcome.ok and "Artist" in outcome.error


def test_numbers_in_prose_count_as_changes():
    from spellforge.agents.specs import same_numbers

    reworded = SPEC.model_copy(update={"description": "A little zap for 3 damage."})
    retuned = SPEC.model_copy(update={"description": "A small zap that deals 2 damage."})
    assert same_numbers(SPEC, reworded)
    assert not same_numbers(SPEC, retuned)
