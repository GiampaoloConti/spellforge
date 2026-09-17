import inspect

import pytest
from conftest import plugin

from spellforge.engine import PluginLoadError, Registry, load_plugin
from spellforge.engine.api import Ctx
from spellforge.engine.context import GameContext
from spellforge.engine.plugins import PLUGIN_GLOBALS, Plugin, _make_namespace
from spellforge.plugins import BUILTIN_PLUGIN_IDS, builtin_source, default_registry

MINIMAL = """
def on_cast(ctx, caster, target):
    ctx.log("hi")

define_spell(id="hello", name="Hello", description="Says hi.", mana_cost=0,
             target="self", on_cast=on_cast)
"""


def test_builtins_load_into_default_registry():
    registry = default_registry()
    assert set(registry.plugins) == set(BUILTIN_PLUGIN_IDS)
    assert {"firebolt", "frost_nova"} <= set(registry.spells)
    assert "frozen" in registry.statuses and "goblin" in registry.monsters
    assert registry.spells["firebolt"].plugin_id == "firebolt"


def test_builtin_sources_have_no_imports():
    for plugin_id in BUILTIN_PLUGIN_IDS:
        assert "import" not in builtin_source(plugin_id)


def test_minimal_plugin_loads():
    loaded = plugin("hello", MINIMAL)
    assert [s.id for s in loaded.spells] == ["hello"]
    assert loaded.spells[0].range == 0


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("def broken(:\n    pass", "syntax error on line 1"),
        ("x = 1", "defines nothing"),
        (MINIMAL.replace('id="hello"', 'id="Hello World"'), "snake_case"),
        (MINIMAL.replace('target="self"', 'target="cone"'), "spell target must be one of"),
        (MINIMAL.replace("mana_cost=0", "mana_cost=-1"), "mana_cost must be an integer"),
        (MINIMAL.replace("on_cast=on_cast", "on_cast=3"), "on_cast must be a function"),
        ("open('secrets.txt')", "NameError"),
        ("import os", "ImportError"),
        (
            "define_monster(id='x1', name='X', description='d', glyph='XX', max_hp=1, attack=0)",
            "glyph must be a single printable character",
        ),
    ],
)
def test_invalid_plugins_are_rejected_with_helpful_errors(source, message):
    with pytest.raises(PluginLoadError, match=message):
        load_plugin("bad", source)


def test_registry_rejects_id_clashes_atomically():
    registry = Registry([plugin("hello", MINIMAL)])
    clash = MINIMAL + MINIMAL.replace('"hello"', '"other"').replace('"Hello"', '"Other"')
    with pytest.raises(PluginLoadError, match="hello"):
        registry.add(plugin("hello_again", clash))
    assert "other" not in registry.spells and "hello_again" not in registry.plugins
    with pytest.raises(PluginLoadError, match="already loaded"):
        registry.add(plugin("hello", MINIMAL.replace('"hello"', '"third"')))


def test_plugin_namespace_is_exactly_the_documented_surface():
    namespace = _make_namespace(Plugin(id="probe", source=""))
    public = {name for name in namespace if not name.startswith("__")}
    assert public == set(PLUGIN_GLOBALS)
    assert "open" not in namespace["__builtins__"]
    assert "__import__" not in namespace["__builtins__"]


def test_every_ctx_method_is_documented_for_plugin_authors():
    abstract = {
        name
        for name, member in inspect.getmembers(Ctx, inspect.isfunction)
        if getattr(member, "__isabstractmethod__", False)
    }
    assert len(abstract) > 20
    for name in abstract:
        doc = inspect.getdoc(getattr(Ctx, name))
        assert doc and len(doc) > 20, f"Ctx.{name} needs a docstring"
    assert not GameContext.__abstractmethods__
