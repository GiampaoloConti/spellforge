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

BUILTIN_PLUGIN_IDS = (
    "goblin",
    "bat",
    "skeleton_archer",
    "slime",
    "orc",
    "goblin_shaman",
    "firebolt",
    "frost_nova",
)


def builtin_source(plugin_id: str) -> str:
    return resources.files(__package__).joinpath(f"{plugin_id}.py").read_text(encoding="utf-8")


@cache
def _load_builtin(plugin_id: str) -> Plugin:
    return load_plugin(plugin_id, builtin_source(plugin_id))


def default_registry() -> Registry:
    """A fresh registry with all builtin plugins (plugin objects are shared and immutable)."""
    return Registry([_load_builtin(plugin_id) for plugin_id in BUILTIN_PLUGIN_IDS])


def builtin_encounters(depth: int) -> list[tuple[str, int]]:
    """Which monsters appear at a given depth, with relative weights.

    Early levels are goblins and bats; archers and slimes join at depth 2, orcs and shamans
    at depth 3, and the tougher monsters grow more common the deeper you go.
    """
    table = [("goblin", max(2, 8 - depth)), ("bat", max(1, 5 - depth))]
    if depth >= 2:
        table += [("skeleton_archer", 1 + depth // 2), ("slime", 2)]
    if depth >= 3:
        table += [("orc", depth - 2), ("goblin_shaman", 1 + depth // 4)]
    return table
