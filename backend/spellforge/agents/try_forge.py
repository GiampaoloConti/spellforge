"""Forge one spell from the command line, against the real API.

    python -m spellforge.agents.try_forge "a spell that turns enemies into sheep"

Reads ANTHROPIC_API_KEY from the environment or the repo's .env file. Costs real tokens.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from spellforge.agents.forge import forge_spell
from spellforge.agents.spell_writer import ClaudeSpellWriter, SpellRequest
from spellforge.plugins import default_registry


async def main(idea: str, attempts: int) -> None:
    registry = default_registry()
    request = SpellRequest(
        idea=idea,
        taken_ids={
            "spells": sorted(registry.spells),
            "statuses": sorted(registry.statuses),
            "monsters": sorted(registry.monsters),
        },
        known_spells=[f"{s.name} ({s.mana_cost} mana)" for s in registry.spells.values()],
    )

    async def progress(stage: str, message: str) -> None:
        print(f"[{stage}] {message}", flush=True)

    writer = ClaudeSpellWriter()
    print(f"model={writer.model} effort={writer.effort}")
    outcome = await forge_spell(request, writer, "forged_cli", attempts, progress)
    for attempt in outcome.attempts:
        print("\n--- failed attempt ---\n" + attempt.draft.source)
        print("problems:", *attempt.problems, sep="\n  ")
    if outcome.ok and outcome.draft:
        print("\n--- plugin ---\n" + outcome.draft.source)
        print("notes:", outcome.draft.notes)
        print("warnings:", outcome.verification.warnings if outcome.verification else [])
    else:
        print("FAILED:", outcome.error)
    print(
        f"\nok={outcome.ok} attempts={len(outcome.attempts) + int(outcome.ok)} "
        f"seconds={outcome.seconds:.1f} input_tokens={outcome.input_tokens} "
        f"output_tokens={outcome.output_tokens}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("idea")
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    asyncio.run(main(args.idea, args.attempts))
