"""The forge pipeline with a scripted writer: real sandbox verification, no API calls."""

import asyncio
import inspect

import pytest

from spellforge.agents.api_docs import plugin_api_reference
from spellforge.agents.forge import forge_spell
from spellforge.agents.llm import Usage
from spellforge.agents.spell_writer import (
    Attempt,
    SpellDraft,
    SpellRequest,
    SpellWriterError,
    request_prompt,
    system_prompt,
)
from spellforge.engine.api import Ctx

GOOD = """
def on_cast(ctx, caster, target):
    victim = ctx.entity_at(target)
    if victim is None:
        ctx.log("The spark fizzles on the floor.")
        return
    ctx.damage(victim.id, 3, source=caster)

define_spell(id="spark", name="Spark", description="A small zap.", mana_cost=2,
             target="tile", range=6, on_cast=on_cast)
"""

CRASHES_ON_EMPTY_TILE = GOOD.replace(
    """    if victim is None:
        ctx.log("The spark fizzles on the floor.")
        return
""",
    "",
)

REQUEST = SpellRequest(
    idea="a little lightning spark",
    taken_ids={
        "spells": ["firebolt", "frost_nova"],
        "statuses": ["frozen"],
        "monsters": ["goblin"],
    },
    known_spells=["Firebolt (3 mana)", "Frost Nova (5 mana)"],
)


class ScriptedWriter:
    def __init__(self, *results: str | Exception) -> None:
        self.results = list(results)
        self.calls: list[list[Attempt]] = []

    async def write(
        self, request: SpellRequest, previous: list[Attempt], on_progress=None
    ) -> SpellDraft:
        self.calls.append(list(previous))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SpellDraft(
            spell_id="spark",
            notes="Zap!",
            source=result,
            usage=Usage(input_tokens=10, output_tokens=5),
        )


def run_forge(writer, **kwargs):
    stages: list[tuple[str, str]] = []

    async def progress(stage: str, message: str) -> None:
        stages.append((stage, message))

    outcome = asyncio.run(
        forge_spell(REQUEST, writer, plugin_id="forged_1", progress=progress, **kwargs)
    )
    return outcome, stages


def test_good_spell_passes_first_time():
    outcome, stages = run_forge(ScriptedWriter(GOOD))
    assert outcome.ok, outcome.verification
    assert outcome.verification.spell_name == "Spark"
    assert outcome.verification.warnings == []
    assert [stage for stage, _ in stages] == ["writing", "testing"]
    assert (outcome.input_tokens, outcome.output_tokens) == (10, 5)


def test_arena_catches_crash_and_feedback_fixes_it():
    writer = ScriptedWriter(CRASHES_ON_EMPTY_TILE, GOOD)
    outcome, stages = run_forge(writer)
    assert outcome.ok
    [failed] = writer.calls[1]
    assert any(
        "cast at an empty floor tile" in p and "AttributeError" in p for p in failed.problems
    )
    assert [stage for stage, _ in stages] == [
        "writing",
        "testing",
        "retrying",
        "writing",
        "testing",
    ]
    assert outcome.input_tokens == 20


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ("import os\n" + GOOD, "imports are not allowed"),
        (GOOD.replace("mana_cost=2", "mana_cost=12"), "mana_cost 12 is outside 1-10"),
        (GOOD.replace('id="spark"', 'id="firebolt"'), "spells id(s) already taken: firebolt"),
        (GOOD + "\ndefine_status(id='frozen', name='F', description='F.')\n", "frozen"),
        (GOOD.replace("define_spell(", "define_spell(bogus=1, "), "failed to load"),
        (GOOD + "\n" + GOOD.replace('"spark"', '"spark_two"'), "exactly one spell"),
    ],
)
def test_rule_violations_are_reported(source, fragment):
    outcome, _ = run_forge(ScriptedWriter(source), max_attempts=1)
    assert not outcome.ok
    assert outcome.error == "the spell kept failing its sandbox tests"
    assert any(fragment in problem for problem in outcome.attempts[0].problems)


def test_no_effect_is_a_warning_not_a_failure():
    idle = GOOD.replace("ctx.damage(victim.id, 3, source=caster)", "return")
    outcome, _ = run_forge(ScriptedWriter(idle))
    assert outcome.ok
    assert any("no visible effect" in w for w in outcome.verification.warnings)


def test_writer_errors_stop_the_forge():
    outcome, _ = run_forge(ScriptedWriter(SpellWriterError("the forge declined this idea")))
    assert not outcome.ok
    assert outcome.error == "the forge declined this idea"


def test_api_reference_documents_every_ctx_method_and_the_limits():
    reference = plugin_api_reference()
    for name in Ctx.__abstractmethods__:
        assert f"`ctx.{name}(" in reference
        assert (inspect.getdoc(getattr(Ctx, name)) or "").splitlines()[0] in reference
    for fragment in ("define_spell(", "define_status(", "define_monster(", "EntityView", "1s"):
        assert fragment in reference


def test_prompts_are_stable_and_carry_the_request():
    assert system_prompt() == system_prompt()  # byte-identical, so prompt caching works
    assert "def on_cast(ctx, caster, target):" in system_prompt()
    prompt = request_prompt(REQUEST)
    assert "<idea>\na little lightning spark\n</idea>" in prompt
    assert "statuses: frozen" in prompt


def test_double_escaped_characters_in_notes_are_decoded():
    from spellforge.agents.llm import unescape as _unescape

    assert _unescape("then 2 \u2014 up to 3") == "then 2 — up to 3"
    assert _unescape("plain text") == "plain text"


@pytest.mark.parametrize(
    ("idea", "expected"),
    [
        ("turn enemies into rocks", True),
        ("a spell that turns the nearest goblin into a harmless frog for 3 turns", True),
        ("polymorph a monster", True),
        ("petrify everything around me", True),
        ("a fireball that explodes", False),
        ("turn undead", False),
        ("heal me and turn my mana into health", True),
    ],
)
def test_transformation_ideas_are_detected(idea, expected):
    from spellforge.agents.forge import changes_appearance

    assert changes_appearance(idea) is expected


def test_transformation_without_a_sprite_is_sent_back():
    writer = ScriptedWriter(GOOD, GOOD)
    request = SpellRequest(
        idea="turn enemies into rocks", taken_ids=REQUEST.taken_ids, known_spells=[]
    )
    outcome = asyncio.run(forge_spell(request, writer, plugin_id="forged_1", max_attempts=2))
    assert not outcome.ok
    assert any("defines no sprite" in p for p in outcome.attempts[0].problems)


def test_request_options_match_each_model():
    from spellforge.agents.llm import request_options

    schema = {"type": "object"}
    opus = request_options("claude-opus-5", "low", schema)
    assert opus["fallbacks"] == "default" and opus["output_config"]["effort"] == "low"
    sonnet = request_options("claude-sonnet-5", "medium", schema)
    assert "fallbacks" not in sonnet and sonnet["thinking"] == {"type": "adaptive"}
    haiku = request_options("claude-haiku-4-5", "low", schema)
    assert set(haiku) == {"output_config"} and "effort" not in haiku["output_config"]
