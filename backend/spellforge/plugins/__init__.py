"""Hand-written builtin plugins.

The other files in this package are NOT imported as Python modules. Each one is plugin
source code, loaded with `spellforge.engine.load_plugin` into a restricted namespace,
exactly like agent-generated plugins. That makes them valid reference examples for the
Coder agent: they use only the plugin API, with no imports.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from spellforge.engine.plugins import Plugin, Registry, load_plugin

BUILTIN_PLUGIN_IDS = ("goblin", "firebolt", "frost_nova")


def builtin_source(plugin_id: str) -> str:
    return resources.files(__package__).joinpath(f"{plugin_id}.py").read_text(encoding="utf-8")


@cache
def _load_builtin(plugin_id: str) -> Plugin:
    return load_plugin(plugin_id, builtin_source(plugin_id))


def default_registry() -> Registry:
    """A fresh registry with all builtin plugins (plugin objects are shared and immutable)."""
    return Registry([_load_builtin(plugin_id) for plugin_id in BUILTIN_PLUGIN_IDS])
