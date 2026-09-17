from __future__ import annotations

import textwrap

import pytest

from spellforge.engine import EventType, Game, Plugin, load_plugin
from spellforge.engine.events import Event
from spellforge.plugins import default_registry


def plugin(plugin_id: str, source: str) -> Plugin:
    """Load a hand-written test plugin (trusted code, so no sandbox needed)."""
    return load_plugin(plugin_id, textwrap.dedent(source))


def events_of(events: list[Event], event_type: EventType) -> list[dict]:
    return [e.data for e in events if e.type is event_type]


@pytest.fixture
def make_game():
    def _make(
        rows: list[str],
        legend: dict[str, str] | None = None,
        spells: tuple[str, ...] = (),
        plugins: tuple[Plugin, ...] = (),
        seed: int = 0,
    ) -> Game:
        registry = default_registry()
        for extra in plugins:
            registry.add(extra)
        return Game.from_ascii(rows, registry, legend or {"g": "goblin"}, seed=seed, spells=spells)

    return _make
