"""The sandbox runs plugin code in a separate process. These tests start real subprocesses."""

import pytest
from conftest import events_of, plugin
from test_api_expressiveness import SHEEP_SPELL

from spellforge.engine import Cast, EventType, Game, InvalidAction, PluginLoadError, Pos, Wait
from spellforge.engine.game import MAX_OPS_PER_TURN
from spellforge.plugins import default_registry
from spellforge.sandbox.host import PluginSandbox, sandbox_environment

ARENA = ["##########", "#@...gg..#", "##########"]


@pytest.fixture
def sandboxes():
    started: list[PluginSandbox] = []

    def start(plugin_id: str, source: str, **options: float):
        sandbox, loaded = PluginSandbox.start(plugin_id, source, **options)
        started.append(sandbox)
        return sandbox, loaded

    yield start
    for sandbox in started:
        sandbox.close()


def spell_source(spell_id: str, body: str, target: str = "self") -> str:
    return (
        "def on_cast(ctx, caster, target):\n"
        + body
        + f"\n\ndefine_spell(id='{spell_id}', name='{spell_id}', description='Test.',"
        + f" mana_cost=1, target='{target}', range=6, on_cast=on_cast)\n"
    )


def game_with(loaded, rows=ARENA, spells=()):
    registry = default_registry()
    registry.add(loaded)
    return Game.from_ascii(rows, registry, {"g": "goblin"}, spells=spells)


def play_sheep_scenario(loaded) -> list[dict]:
    game = game_with(loaded, spells=("explosive_sheep",))
    game.submit(Cast("explosive_sheep", Pos(5, 1)))
    game.submit(Wait())
    game.submit(Wait())
    return [e.to_dict() for e in game.history]


def test_sandboxed_plugin_behaves_exactly_like_in_process(sandboxes):
    _, remote = sandboxes("explosive_sheep", SHEEP_SPELL)
    local = plugin("explosive_sheep", SHEEP_SPELL)  # hand-written test code, safe in-process
    remote_history = play_sheep_scenario(remote)
    assert remote_history == play_sheep_scenario(local)
    assert any(e["type"] == "died" for e in remote_history)  # the sheep exploded


def test_static_problems_are_reported_before_any_process_starts():
    with pytest.raises(PluginLoadError, match="line 1: imports are not allowed"):
        PluginSandbox.start("bad", "import os")


def test_load_errors_from_the_worker_are_reported(sandboxes):
    with pytest.raises(PluginLoadError, match="mana_cost must be an integer"):
        sandboxes("bad", spell_source("bad", "    pass").replace("mana_cost=1", "mana_cost=-5"))


def test_infinite_loop_while_loading_times_out(sandboxes):
    with pytest.raises(PluginLoadError, match="did not respond"):
        sandboxes("spin", "while True:\n    pass\n", load_timeout=2.0)


def test_infinite_loop_in_a_hook_is_killed_and_the_game_continues(sandboxes):
    _, loaded = sandboxes("spin", spell_source("spin", "    while True:\n        pass"))
    game = game_with(loaded, spells=("spin",))
    events = game.submit(Cast("spin"))
    reasons = {e["plugin"]: e["reason"] for e in events_of(events, EventType.PLUGIN_DISABLED)}
    assert "did not respond within 1s" in reasons["spin"]
    game.submit(Wait())
    with pytest.raises(InvalidAction, match="disabled"):
        game.submit(Cast("spin"))


def test_memory_bomb_is_contained(sandboxes):
    _, loaded = sandboxes("bomb", spell_source("bomb", "    hoard = [0] * (10 ** 9)"))
    game = game_with(loaded, spells=("bomb",))
    events = game.submit(Cast("bomb"))
    assert "bomb" in {e["plugin"] for e in events_of(events, EventType.PLUGIN_DISABLED)}
    game.submit(Wait())


def test_plugin_errors_keep_their_original_type(sandboxes):
    _, loaded = sandboxes("oops", spell_source("oops", "    return 1 / 0"))
    game = game_with(loaded, spells=("oops",))
    events = game.submit(Cast("oops"))
    assert events_of(events, EventType.PLUGIN_DISABLED)[0]["reason"] == (
        "ZeroDivisionError: division by zero"
    )


def test_api_misuse_counts_even_if_the_plugin_catches_it(sandboxes):
    body = "    try:\n        ctx.damage('goblin', 5)\n    except:\n        ctx.log('hid it')"
    _, loaded = sandboxes("sly", spell_source("sly", body))
    game = game_with(loaded, spells=("sly",))
    events = game.submit(Cast("sly"))
    [disabled] = events_of(events, EventType.PLUGIN_DISABLED)
    assert "entity id must be an int" in disabled["reason"]


def test_action_budget_applies_across_the_process_boundary(sandboxes):
    body = "    while True:\n        ctx.turn_number()"
    _, loaded = sandboxes("spam", spell_source("spam", body))
    game = game_with(loaded, spells=("spam",))
    events = game.submit(Cast("spam"))
    [disabled] = events_of(events, EventType.PLUGIN_DISABLED)
    assert f"more than {MAX_OPS_PER_TURN} API calls" in disabled["reason"]


def test_worker_validates_source_too(sandboxes):
    """Defense in depth: even if the host check were skipped, the worker refuses bad code."""
    sandbox = PluginSandbox()
    try:
        with pytest.raises(PluginLoadError, match="imports are not allowed"):
            sandbox._load("sneaky", "import os\n")
    finally:
        sandbox.close()


def test_sandbox_environment_carries_no_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    env = sandbox_environment()
    assert "ANTHROPIC_API_KEY" not in env
    assert set(env) <= {"SYSTEMROOT"}


def test_closed_sandbox_rejects_calls(sandboxes):
    sandbox, loaded = sandboxes("zap", spell_source("zap", "    ctx.log('zap')"))
    game = game_with(loaded, spells=("zap",))
    sandbox.close()
    events = game.submit(Cast("zap"))
    assert "not running" in events_of(events, EventType.PLUGIN_DISABLED)[0]["reason"]
