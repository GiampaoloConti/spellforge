"""The forge pipeline (M3): write a spell with one agent, verify it, retry with feedback.

    idea ──► Spell Writer ──► verify in sandbox ──► ok ──► ready to hot-load
                 ▲                    │
                 └──── problems ──────┘   (up to `max_attempts`)

Progress is reported through an async callback so the game can show it while the player
keeps playing. In M4 the single writer is replaced by a team of agents.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from spellforge.agents.spell_writer import (
    Attempt,
    SpellDraft,
    SpellRequest,
    SpellWriter,
    SpellWriterError,
)
from spellforge.agents.verify import Verification, verify_spell_source

DEFAULT_MAX_ATTEMPTS = 2

TRANSFORMATION = re.compile(
    r"\b(turns?|turning|transform\w*|morph\w*|chang\w*|becom\w*)\b[^.!?]{0,60}\binto\b"
    r"|\bpolymorph|\bpetrif|\bdisguise",
    re.IGNORECASE,
)
MISSING_SPRITE = (
    "the idea changes how creatures look, but the plugin defines no sprite: draw one with "
    "define_sprite and use it via define_status(appearance=...) or define_monster(sprite=...)"
)


def changes_appearance(idea: str) -> bool:
    """Heuristic: does the player's idea transform creatures into something else?"""
    return TRANSFORMATION.search(idea) is not None


ProgressCallback = Callable[[str, str], Awaitable[None]]


async def _no_progress(stage: str, message: str) -> None:
    return None


@dataclass
class ForgeOutcome:
    ok: bool
    draft: SpellDraft | None = None
    verification: Verification | None = None
    error: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def input_tokens(self) -> int:
        drafts = [a.draft for a in self.attempts] + ([self.draft] if self.ok and self.draft else [])
        return sum(d.input_tokens for d in drafts)

    @property
    def output_tokens(self) -> int:
        drafts = [a.draft for a in self.attempts] + ([self.draft] if self.ok and self.draft else [])
        return sum(d.output_tokens for d in drafts)


async def forge_spell(
    request: SpellRequest,
    writer: SpellWriter,
    plugin_id: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    progress: ProgressCallback = _no_progress,
) -> ForgeOutcome:
    started = time.perf_counter()
    outcome = ForgeOutcome(ok=False)
    for attempt_number in range(1, max_attempts + 1):
        await progress(
            "writing",
            "The Spell Writer is designing your spell…"
            if attempt_number == 1
            else f"Fixing the spell (attempt {attempt_number} of {max_attempts})…",
        )

        async def note(message: str) -> None:
            await progress("writing", message)

        try:
            draft = await writer.write(request, outcome.attempts, note)
        except SpellWriterError as exc:
            outcome.error = str(exc)
            break

        await progress("testing", f"Testing {draft.spell_id} in the sandbox…")
        verification = await asyncio.to_thread(
            verify_spell_source, plugin_id, draft.source, request.taken_ids
        )
        if verification.ok and changes_appearance(request.idea) and not verification.sprite_count:
            verification.ok = False
            verification.problems.append(MISSING_SPRITE)
        if verification.ok:
            outcome.ok = True
            outcome.draft = draft
            outcome.verification = verification
            break
        outcome.attempts.append(Attempt(draft, verification.problems))
        outcome.verification = verification
        await progress("retrying", f"The spell failed its tests: {verification.problems[0]}")
    else:
        outcome.error = "the spell kept failing its sandbox tests"

    outcome.seconds = time.perf_counter() - started
    return outcome
