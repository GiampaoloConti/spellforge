"""The agent team that forges spells (M4).

    idea ─► Designer ─► spec ─┬─► Balancer ─► approved spec ─┐
                              ├─► Coder (speculative) ────────┼─► plugin + art ─► Tester ─► ok
                              └─► Artist (sprite) ────────────┘        ▲             │
                                                                        └─ problems ──┘

Each agent has its own system prompt and context and hands off a validated structure
(`specs.py`). As soon as the Designer finishes, three agents work in parallel: the Balancer
reviews the spec, the Coder starts implementing it speculatively, and the Artist draws the
sprite if one is needed. If the Balancer approves the numbers as designed, the Coder's head
start is kept; if it adjusts them, the speculative draft is cancelled and the Coder restarts
from the approved spec. The Artist's sprite is attached to the plugin before testing.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from spellforge.agents.artist import Artist
from spellforge.agents.balancer import Balancer
from spellforge.agents.coder import Coder, spell_task
from spellforge.agents.designer import Designer
from spellforge.agents.forge import (
    DEFAULT_MAX_ATTEMPTS,
    ForgeOutcome,
    ProgressCallback,
    _no_progress,
    changes_appearance,
)
from spellforge.agents.llm import AgentError, Usage
from spellforge.agents.specs import SpellSpec, same_numbers, spec_summary
from spellforge.agents.spell_writer import Attempt, SpellDraft, SpellRequest
from spellforge.agents.tester import Tester


async def cancel(task: asyncio.Task[Any] | None) -> None:
    """Cancel a background task and wait for it, swallowing its cancellation or failure."""
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, AgentError):
        pass


class TeamForge:
    mode = "team"

    def __init__(
        self,
        designer: Designer,
        balancer: Balancer,
        coder: Coder,
        artist: Artist | None = None,
        tester: Tester | None = None,
        max_code_attempts: int = DEFAULT_MAX_ATTEMPTS,
        speculative: bool = True,
    ) -> None:
        self.designer = designer
        self.balancer = balancer
        self.coder = coder
        self.artist = artist
        self.tester = tester or Tester()
        self.max_code_attempts = max_code_attempts
        self.speculative = speculative

    async def forge(
        self, request: SpellRequest, plugin_id: str, progress: ProgressCallback = _no_progress
    ) -> ForgeOutcome:
        started = time.perf_counter()
        outcome = ForgeOutcome(ok=False)
        usage: dict[str, Usage] = defaultdict(Usage)
        team: dict[str, Any] = {"design": None, "review": None, "speculation": "off"}
        outcome.team = team
        speculative: asyncio.Task[SpellDraft] | None = None
        art: asyncio.Task[tuple[str, Usage]] | None = None
        sprite_id = f"{plugin_id}_art" if self.artist is not None else None
        art_source: str | None = None

        def start_art(spec: SpellSpec) -> asyncio.Task[tuple[str, Usage]] | None:
            if self.artist is None:
                return None
            description = spec.sprite_description or f"{spec.name}: {spec.description}"
            return asyncio.create_task(
                self.artist.draw(f"{plugin_id}_art", description, notes("drawing"))
            )

        def notes(stage: str) -> Any:
            async def note(message: str) -> None:
                await progress(stage, message)

            return note

        try:
            # 1. Design.
            await progress("designing", "The Designer is shaping your idea into a spec…")
            spec, used = await self.designer.design(request, notes("designing"))
            usage["designer"] += used
            team["design"] = spec_summary(spec)
            await progress(
                "designing", f"Designed “{spec.name}”.", done=True, detail=spec.description
            )

            # 2. Balance, with the Coder and the Artist starting in parallel.
            needs_art = spec.needs_sprite or changes_appearance(request.idea)
            if needs_art:
                art = start_art(spec)
                if art is not None:
                    await progress("drawing", "The Artist starts drawing the sprite…")
            art_id = sprite_id if art is not None else None
            if self.speculative:
                speculative = asyncio.create_task(
                    self.coder.write(self._task(request, spec, art_id), [], notes("coding"))
                )
                team["speculation"] = "started"
                await progress("coding", "The Coder starts early while the Balancer reviews…")
            await progress("balancing", "The Balancer is hunting for exploits…")
            review, used = await self.balancer.review_spell(
                spec, request.known_spells, notes("balancing")
            )
            usage["balancer"] += used
            approved = self._with_sprite_if_needed(request, review.spec)
            team["review"] = {
                "verdict": review.verdict,
                "rationale": review.rationale,
                "changes": [change.model_dump() for change in review.changes],
                "exploits_considered": review.exploits_considered,
            }
            await progress(
                "balancing",
                {
                    "approve": "The Balancer approved the design.",
                    "adjust": "The Balancer adjusted the numbers.",
                    "reject": "The Balancer rejected the design.",
                }[review.verdict],
                done=True,
                verdict=review.verdict,
                detail=review.rationale,
                changes=team["review"]["changes"],
            )
            if review.verdict == "reject":
                await cancel(speculative)
                await cancel(art)
                team["speculation"] = "discarded" if speculative else "off"
                outcome.error = f"the Balancer rejected it: {review.rationale}"
                return outcome

            if approved.needs_sprite and art is None:
                art = start_art(approved)
                art_id = sprite_id if art is not None else None
                if art is not None:
                    await progress("drawing", "The Artist starts drawing the sprite…")

            # 3. Code: keep the speculative draft if the numbers survived review.
            draft: SpellDraft | None = None
            if speculative is not None and same_numbers(spec, approved):
                try:
                    draft = await speculative
                    team["speculation"] = "used"
                except AgentError:
                    team["speculation"] = "failed"
                    await progress("coding", "The early draft failed; the Coder tries again…")
            elif speculative is not None:
                team["speculation"] = "discarded"
                await cancel(speculative)
                await progress("coding", "The Coder restarts from the balanced spec…")
            else:
                await progress("coding", "The Coder is implementing the spec…")
            if draft is None:
                draft = await self.coder.write(
                    self._task(request, approved, art_id), [], notes("coding")
                )
            usage["coder"] += draft.usage
            if art is not None:
                art_source, used = await art
                usage["artist"] += used
                await progress("drawing", "The Artist finished the sprite.", done=True)

            # 4. Test. Code problems go back to the Coder; a spell measured over budget in the
            #    balance probe goes back to the Balancer with the measurements.
            code_attempts = 1
            rebalanced = False
            while True:
                await progress("coding", f"The Coder wrote {draft.spell_id}.", done=True)
                await progress("testing", "The Tester is running the spell in the sandbox…")
                draft = self._with_art(draft, art_source)
                report = await asyncio.to_thread(
                    self.tester.test_spell, plugin_id, draft.source, approved, request.taken_ids
                )
                outcome.verification = report
                if report.ok:
                    await progress(
                        "testing", "All tests passed, and it is within budget.", done=True
                    )
                    outcome.ok = True
                    outcome.draft = draft
                    break
                outcome.attempts.append(Attempt(draft, report.problems))
                code_problems = [p for p in report.problems if p not in report.balance_problems]

                if not code_problems and report.balance_problems and not rebalanced:
                    rebalanced = True
                    team["rebalance"] = report.balance_problems
                    await progress(
                        "balancing",
                        "The balance probe measured it as too strong; back to the Balancer…",
                        detail="; ".join(report.balance_problems),
                    )
                    review, used = await self.balancer.review_spell(
                        approved,
                        request.known_spells,
                        notes("balancing"),
                        measurements=report.balance_problems,
                    )
                    usage["balancer"] += used
                    team["review"] = {
                        "verdict": review.verdict,
                        "rationale": review.rationale,
                        "changes": (team["review"] or {}).get("changes", [])
                        + [change.model_dump() for change in review.changes],
                        "exploits_considered": review.exploits_considered,
                    }
                    await progress(
                        "balancing",
                        "The Balancer rejected it."
                        if review.verdict == "reject"
                        else "The Balancer rebalanced it.",
                        done=True,
                        verdict=review.verdict,
                        detail=review.rationale,
                        changes=team["review"]["changes"],
                    )
                    if review.verdict == "reject":
                        outcome.error = f"the Balancer rejected it: {review.rationale}"
                        break
                    approved = self._with_sprite_if_needed(request, review.spec)
                    await progress("coding", "The Coder implements the rebalanced spec…")
                    draft = await self.coder.write(
                        self._task(request, approved, art_id), [], notes("coding")
                    )
                    usage["coder"] += draft.usage
                    continue

                if code_attempts >= self.max_code_attempts or not code_problems:
                    outcome.error = (
                        "the spell stayed over budget after rebalancing"
                        if not code_problems
                        else "the spell kept failing its sandbox tests"
                    )
                    break
                code_attempts += 1
                await progress(
                    "retrying",
                    f"The Tester found a problem: {code_problems[0]}",
                    detail="; ".join(code_problems[:3]),
                )
                draft = await self.coder.write(
                    self._task(request, approved, art_id),
                    [
                        Attempt(
                            a.draft, [p for p in a.problems if not p.startswith("balance probe")]
                        )
                        for a in outcome.attempts
                    ],
                    notes("coding"),
                )
                usage["coder"] += draft.usage
        except AgentError as exc:
            outcome.error = str(exc)
        finally:
            for pending in (speculative, art):
                if pending is not None and not pending.done():
                    await cancel(pending)
            outcome.seconds = time.perf_counter() - started
            for used in usage.values():
                outcome.usage = outcome.usage + used
            team["agents"] = {
                role: {
                    "model": used.model,
                    "seconds": round(used.seconds, 1),
                    "tokens": used.input_tokens + used.output_tokens,
                    "cost_usd": round(used.cost_usd, 4),
                }
                for role, used in usage.items()
            }
        return outcome

    @staticmethod
    def _task(request: SpellRequest, spec: SpellSpec, sprite_id: str | None = None) -> str:
        return spell_task(request.idea, spec, request.taken_ids, sprite_id)

    @staticmethod
    def _with_art(draft: SpellDraft, art_source: str | None) -> SpellDraft:
        """The Coder's plugin with the Artist's sprite appended (built from literals)."""
        if art_source is None or art_source in draft.source:
            return draft
        source = (
            f"{draft.source.rstrip()}\n\n\n# ---- art (drawn by the Artist) ----\n\n{art_source}"
        )
        return SpellDraft(
            spell_id=draft.spell_id,
            notes=draft.notes,
            source=source,
            transcript=draft.transcript,
            usage=draft.usage,
        )

    @staticmethod
    def _with_sprite_if_needed(request: SpellRequest, spec: SpellSpec) -> SpellSpec:
        """Transformation ideas always need art, even if the design forgot to ask for it."""
        if changes_appearance(request.idea) and not spec.needs_sprite:
            return spec.model_copy(update={"needs_sprite": True})
        return spec
