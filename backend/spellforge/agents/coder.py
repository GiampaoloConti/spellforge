"""The Coder: implements an approved spec as a plugin, exactly.

It gets the approved spec (the authority on every number), the player's idea for flavor
only, the full plugin API reference and working examples. When the Tester finds problems,
the Coder gets its previous answer plus the test report and fixes the plugin.
"""

from __future__ import annotations

from typing import Any

import anthropic

from spellforge.agents.llm import AgentConfig, ProgressNote, structured_call
from spellforge.agents.prompts import (
    feedback_prompt,
    plugin_rules,
    reference_examples,
    taken_ids_text,
)
from spellforge.agents.specs import MonsterSpec, SpellSpec
from spellforge.agents.spell_writer import Attempt, SpellDraft, draft_from_reply

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "string",
            "description": "1-2 sentences on implementation choices (for the other agents).",
        },
        "content_id": {
            "type": "string",
            "description": "The id passed to define_spell (or define_monster for monsters).",
        },
        "plugin_source": {"type": "string", "description": "The complete plugin file."},
    },
    "required": ["notes", "content_id", "plugin_source"],
    "additionalProperties": False,
}


def system_prompt() -> str:
    return f"""\
You are the Coder in Spellforge's forge. Other agents designed and balanced a spell or \
monster and hand you its approved spec. You implement it as a plugin file that is loaded \
into the running game.

# How to work
- The spec is the authority. Use its numbers exactly: mana_cost, cooldown, range, target, \
damage, heal, durations, radius, target counts, HP and attack. Do not rebalance.
- Implement every effect and handle every listed edge case.
- A Tester runs your plugin in a sandbox and checks it against the spec; if it reports \
problems, fix them.

# Spell plugins
- Exactly one `define_spell`, whose mana_cost, cooldown, target and range match the spec. \
Define the statuses, monsters and sprites the spell uses in the same file.

# Monster plugins
- Exactly one main `define_monster` (listed first) with max_hp and attack from the spec, a \
sprite, and an `act` function implementing the spec's behaviour. No `define_spell`. Passive \
abilities can be a status the monster applies to itself on its first turn (see the slime \
example). Extra monsters it spawns may follow the main one.

# Plugin rules
{plugin_rules()}

{reference_examples(("firebolt", "frost_nova", "slime", "skeleton_archer", "goblin"))}

# Output
Return JSON with `notes`, `content_id` and `plugin_source` (the complete file, no markdown \
fences)."""


def art_note(sprite_id: str | None) -> str:
    if sprite_id is None:
        return ""
    return f"""

Art: the Artist is drawing the sprite `{sprite_id}` for you from the spec's sprite description, \
and it will be added to your file. Do not call define_sprite yourself; use \
`appearance="{sprite_id}"` (for a status) or `sprite="{sprite_id}"` (for a monster)."""


def spell_task(
    idea: str, spec: SpellSpec, taken_ids: dict[str, list[str]], sprite_id: str | None = None
) -> str:
    return f"""\
Implement this approved spell spec:
```json
{spec.model_dump_json(indent=2)}
```

The player's original idea, for flavor and messages only (the spec wins on every number):
<idea>
{idea}
</idea>

Ids already taken in this game:
{taken_ids_text(taken_ids)}{art_note(sprite_id)}"""


def monster_task(
    spec: MonsterSpec, taken_ids: dict[str, list[str]], sprite_id: str | None = None
) -> str:
    return f"""\
Implement this approved monster spec:
```json
{spec.model_dump_json(indent=2)}
```

Ids already taken in this game:
{taken_ids_text(taken_ids)}{art_note(sprite_id)}"""


class Coder:
    role = "Coder"

    def __init__(self, client: anthropic.AsyncAnthropic, config: AgentConfig | None = None) -> None:
        self.client = client
        self.config = config or AgentConfig.for_role("coder")

    async def write(
        self,
        task: str,
        previous: list[Attempt],
        on_progress: ProgressNote | None = None,
    ) -> SpellDraft:
        """Write (or, with `previous` failed attempts, fix) the plugin for `task`."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        for attempt in previous:
            messages.append({"role": "assistant", "content": attempt.draft.transcript})
            messages.append({"role": "user", "content": feedback_prompt(attempt.problems)})
        reply = await structured_call(
            self.client,
            self.config,
            system=system_prompt(),
            messages=messages,
            schema=OUTPUT_SCHEMA,
            role=self.role,
            on_progress=on_progress,
        )
        data = dict(reply.data)
        data["spell_id"] = data.pop("content_id", "")
        return draft_from_reply(data, reply.content, reply.usage)
