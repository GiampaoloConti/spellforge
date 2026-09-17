"""Forge one spell from the command line, against the real API.

    python -m spellforge.agents.try_forge "a spell that turns enemies into sheep"
    python -m spellforge.agents.try_forge --mode single "chain lightning"

Reads ANTHROPIC_API_KEY from the environment or the repo's .env file. Costs real tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from spellforge.agents.factory import make_spell_forge
from spellforge.agents.spell_writer import SpellRequest
from spellforge.plugins import default_registry


def request_for(idea: str) -> SpellRequest:
    registry = default_registry()
    return SpellRequest(
        idea=idea,
        taken_ids={
            "spells": sorted(registry.spells),
            "statuses": sorted(registry.statuses),
            "monsters": sorted(registry.monsters),
            "sprites": sorted(registry.sprites),
        },
        known_spells=[f"{s.name} ({s.mana_cost} mana)" for s in registry.spells.values()],
    )


async def main(idea: str, mode: str) -> None:
    async def progress(stage: str, message: str, **details: Any) -> None:
        extra = f"  {json.dumps(details)}" if details else ""
        print(f"[{stage}] {message}{extra}", flush=True)

    forge = make_spell_forge(mode)
    outcome = await forge.forge(request_for(idea), "forged_cli", progress)
    for attempt in outcome.attempts:
        print("\n--- failed attempt ---\n" + attempt.draft.source)
        print("problems:", *attempt.problems, sep="\n  ")
    if outcome.ok and outcome.draft:
        print("\n--- plugin ---\n" + outcome.draft.source)
        print("warnings:", outcome.verification.warnings if outcome.verification else [])
    else:
        print("FAILED:", outcome.error)
    if outcome.team:
        print("\nteam:", json.dumps(outcome.team, indent=1))
    print(
        f"\nmode={forge.mode} ok={outcome.ok} attempts={len(outcome.attempts) + int(outcome.ok)} "
        f"seconds={outcome.seconds:.1f} cost=${outcome.cost_usd:.3f}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea")
    parser.add_argument("--mode", choices=("team", "single"), default="team")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    asyncio.run(main(args.idea, args.mode))
