"""Benchmark the forge across models and effort levels on the same spell ideas.

    python -m spellforge.agents.bench_forge --out ../docs/evals/forge-models.json

Each run is the full pipeline (writer + sandbox verification + one retry), so "ok" means
the spell would have reached the player. Costs real tokens (about $1 for the default grid).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from spellforge.agents.artist import Artist
from spellforge.agents.balancer import Balancer
from spellforge.agents.coder import Coder
from spellforge.agents.designer import Designer
from spellforge.agents.forge import SingleAgentForge, SpellForge
from spellforge.agents.llm import AgentConfig
from spellforge.agents.spell_writer import ClaudeSpellWriter, SpellDraft, SpellRequest
from spellforge.agents.team import TeamForge
from spellforge.plugins import default_registry

IDEAS = [
    "turn enemies into rocks for a few turns",
    "chain lightning that jumps between up to 3 enemies, weaker with each jump",
    "summon a spirit wolf that fights beside me for 5 turns",
]

CONFIGS = [
    ("claude-opus-5", "high"),
    ("claude-opus-5", "low"),
    ("claude-sonnet-5", "medium"),
    ("claude-sonnet-5", "low"),
    ("claude-haiku-4-5", "-"),
]


def cost(draft: SpellDraft) -> float:
    return draft.usage.cost_usd


@dataclass
class Run:
    model: str
    effort: str
    idea: str
    result: dict[str, Any]


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


PRESETS: dict[str, dict[str, tuple[str, str]]] = {
    # name -> role -> (model, effort); "writer" means the single-agent baseline.
    "single-opus": {"writer": ("claude-opus-5", "low")},
    "team-opus": {
        "designer": ("claude-opus-5", "low"),
        "balancer": ("claude-opus-5", "low"),
        "coder": ("claude-opus-5", "low"),
    },
    "team-mixed": {
        "designer": ("claude-sonnet-5", "low"),
        "balancer": ("claude-sonnet-5", "low"),
        "coder": ("claude-opus-5", "low"),
    },
    "team-artist": {
        "designer": ("claude-sonnet-5", "low"),
        "balancer": ("claude-sonnet-5", "low"),
        "coder": ("claude-sonnet-5", "low"),
        "artist": ("claude-opus-5", "low"),
    },
}


def build_forge(preset: str, client: anthropic.AsyncAnthropic) -> SpellForge:
    roles = {role: AgentConfig(*config) for role, config in PRESETS[preset].items()}
    if "writer" in roles:
        writer = ClaudeSpellWriter(client, roles["writer"].model, roles["writer"].effort)
        return SingleAgentForge(writer)
    return TeamForge(
        Designer(client, roles["designer"]),
        Balancer(client, roles["balancer"]),
        Coder(client, roles["coder"]),
        Artist(client, roles["artist"]) if "artist" in roles else None,
    )


async def run_one(model: str, effort: str, idea: str, index: int, limit: asyncio.Semaphore) -> Run:
    """`model` is a model id (single writer at `effort`) or a preset name from PRESETS."""
    async with limit:
        client = anthropic.AsyncAnthropic()
        if model in PRESETS:
            forge = build_forge(model, client)
        else:
            forge = SingleAgentForge(
                ClaudeSpellWriter(client, model, effort if effort != "-" else "low")
            )
        started = time.perf_counter()
        outcome = await forge.forge(request_for(idea), f"bench_{index}")
        drafts = [a.draft for a in outcome.attempts] + (
            [outcome.draft] if outcome.ok and outcome.draft else []
        )
        final = drafts[-1] if drafts else None
        result = {
            "ok": outcome.ok,
            "error": outcome.error,
            "attempts": len(drafts),
            "seconds": round(time.perf_counter() - started, 1),
            "input_tokens": outcome.usage.input_tokens,
            "cache_read_tokens": outcome.usage.cache_read_tokens,
            "output_tokens": outcome.usage.output_tokens,
            "cost_usd": round(outcome.cost_usd, 4),
            "spell": outcome.verification.spell_name if outcome.verification else "",
            "sprites": outcome.verification.sprite_count if outcome.verification else 0,
            "warnings": outcome.verification.warnings if outcome.verification else [],
            "problems": [a.problems for a in outcome.attempts],
            "notes": final.notes if final else "",
            "source": final.source if final else "",
            "team": outcome.team,
        }
        verdict = (outcome.team or {}).get("review") or {}
        print(
            f"{model:18} {effort:6} ok={outcome.ok!s:5} attempts={result['attempts']} "
            f"{result['seconds']:5.1f}s ${result['cost_usd']:.3f} "
            f"{verdict.get('verdict', ''):7} {(outcome.team or {}).get('speculation', ''):9} "
            f"{idea[:36]}",
            flush=True,
        )
        return Run(model, effort, idea, result)


def summarize(runs: list[Run], configs: list[tuple[str, str]]) -> str:
    lines = [
        "| Model | Effort | Success | Avg attempts | Avg time | Avg cost "
        "| Sprites drawn when needed |",
        "|---|---|---|---|---|---|---|",
    ]
    for model, effort in configs:
        group = [r for r in runs if (r.model, r.effort) == (model, effort)]
        if not group:
            continue
        ok = [r for r in group if r.result["ok"]]
        needs_art = [r for r in ok if "rocks" in r.idea or "wolf" in r.idea]
        drawn = sum(1 for r in needs_art if r.result["sprites"] > 0)
        lines.append(
            f"| {model} | {effort} | {len(ok)}/{len(group)} "
            f"| {sum(r.result['attempts'] for r in group) / len(group):.1f} "
            f"| {sum(r.result['seconds'] for r in group) / len(group):.1f}s "
            f"| ${sum(r.result['cost_usd'] for r in group) / len(group):.3f} "
            f"| {drawn}/{len(needs_art)} |"
        )
    return "\n".join(lines)


async def main(
    out: Path | None, concurrency: int, configs: list[tuple[str, str]], repeats: int
) -> None:
    limit = asyncio.Semaphore(concurrency)
    grid = [(config, idea) for config in configs for idea in IDEAS for _ in range(repeats)]
    jobs = [
        run_one(model, effort, idea, i, limit) for i, ((model, effort), idea) in enumerate(grid)
    ]
    runs = await asyncio.gather(*jobs)
    table = summarize(runs, configs)
    print("\n" + table)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "ideas": IDEAS,
                    "configs": configs,
                    "repeats": repeats,
                    "summary": table,
                    "runs": [r.__dict__ for r in runs],
                },
                indent=1,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--configs",
        help="comma-separated model:effort pairs, e.g. claude-opus-5:low,claude-sonnet-5:low",
    )
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    configs = CONFIGS
    if args.configs:  # "model:effort" pairs, or preset names from PRESETS
        configs = [
            tuple(c.split(":", 1)) if ":" in c else (c, "-") for c in args.configs.split(",")
        ]
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    asyncio.run(main(args.out, args.concurrency, configs, args.repeats))
