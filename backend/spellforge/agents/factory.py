"""Builds the configured forge: the agent team (default) or the single-agent baseline.

`SPELLFORGE_FORGE_MODE=single` selects the baseline. One shared Anthropic client means one
connection pool for every agent.
"""

from __future__ import annotations

import os

import anthropic

from spellforge.agents.artist import Artist
from spellforge.agents.balancer import Balancer
from spellforge.agents.coder import Coder
from spellforge.agents.designer import Designer
from spellforge.agents.dungeon_master import DungeonMaster, DungeonMasterAgent
from spellforge.agents.forge import SingleAgentForge, SpellForge
from spellforge.agents.spell_writer import ClaudeSpellWriter
from spellforge.agents.team import TeamForge

MODES = ("team", "single")


def make_spell_forge(
    mode: str | None = None, client: anthropic.AsyncAnthropic | None = None
) -> SpellForge:
    mode = mode or os.environ.get("SPELLFORGE_FORGE_MODE", "team")
    if mode not in MODES:
        raise ValueError(f"unknown forge mode {mode!r}; expected one of {MODES}")
    client = client or anthropic.AsyncAnthropic()
    if mode == "single":
        return SingleAgentForge(ClaudeSpellWriter(client))
    return TeamForge(Designer(client), Balancer(client), Coder(client), Artist(client))


def make_dungeon_master(client: anthropic.AsyncAnthropic | None = None) -> DungeonMaster | None:
    """The Dungeon Master, unless disabled with SPELLFORGE_DUNGEON_MASTER=off."""
    if os.environ.get("SPELLFORGE_DUNGEON_MASTER", "on").lower() in ("off", "0", "false"):
        return None
    client = client or anthropic.AsyncAnthropic()
    return DungeonMaster(
        DungeonMasterAgent(client), Balancer(client), Coder(client), Artist(client)
    )
