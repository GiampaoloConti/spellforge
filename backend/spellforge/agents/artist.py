"""The Artist: draws 16x16 pixel art for spells and monsters, in parallel with the other agents.

Separating art from code lets the Coder run on a faster model while a stronger model draws,
and both happen at the same time. The Artist returns plain data; the orchestrator attaches it
to the Coder's plugin as a `define_sprite(...)` call built from literals, so no model-written
code is involved.
"""

from __future__ import annotations

from typing import Any

import anthropic

from spellforge.agents.llm import AgentConfig, AgentError, ProgressNote, Usage, structured_call
from spellforge.engine import PluginLoadError
from spellforge.engine.api import MAX_SPRITE_COLORS, SPRITE_SIZE
from spellforge.engine.plugins import normalize_sprite
from spellforge.plugins import builtin_source

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "palette": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "One character, not '.'."},
                    "color": {"type": "string", "description": "Hex color like #5caa3c."},
                },
                "required": ["key", "color"],
                "additionalProperties": False,
            },
        },
        "rows": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"{SPRITE_SIZE} rows of {SPRITE_SIZE} characters, top row first.",
        },
    },
    "required": ["palette", "rows"],
    "additionalProperties": False,
}


def system_prompt() -> str:
    return f"""\
You are the Artist of Spellforge, a roguelike drawn in 16x16 pixel art on a dark dungeon floor. \
Other agents are building a spell or monster; you draw the sprite it needs.

# Format
- `rows`: exactly {SPRITE_SIZE} strings of exactly {SPRITE_SIZE} characters, top row first. \
Count carefully.
- Each character is a palette key, or "." for a transparent pixel.
- `palette`: 3-{MAX_SPRITE_COLORS} single-character keys mapped to hex colors.

# Style
- Readable at a glance: a bold silhouette that fills most of the 16x16 box, facing right, \
feet or base on the bottom rows.
- A 1-pixel dark outline ("#140d1c") around the shape so it reads on the dark floor.
- 3-6 colors: a base, a lighter highlight on the top-left, a darker shade on the \
bottom-right, plus accents (eyes, runes, glow).
- Match the game's look: here are sprites from the game.

# Examples
```python
{_example_sprites()}
```"""


def _example_sprites() -> str:
    """The `define_sprite` blocks of two builtin monsters, as style references."""
    blocks = []
    for name in ("goblin", "orc"):
        source = builtin_source(name)
        blocks.append(source[source.index("define_sprite(") :].strip())
    return "\n\n".join(blocks)


def sprite_source(sprite_id: str, palette: dict[str, str], rows: list[str]) -> str:
    """A `define_sprite` call built from validated literals (safe to append to a plugin)."""
    colors = "".join(f"        {key!r}: {color!r},\n" for key, color in palette.items())
    lines = "".join(f"        {row!r},\n" for row in rows)
    return (
        f"define_sprite(\n    id={sprite_id!r},\n    palette={{\n{colors}    }},\n"
        f"    rows=[\n{lines}    ],\n)\n"
    )


class Artist:
    role = "Artist"

    def __init__(self, client: anthropic.AsyncAnthropic, config: AgentConfig | None = None) -> None:
        self.client = client
        self.config = config or AgentConfig.for_role("artist")

    async def draw(
        self, sprite_id: str, description: str, on_progress: ProgressNote | None = None
    ) -> tuple[str, Usage]:
        """Draw the sprite; returns its `define_sprite` source. One repair turn if invalid."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"Draw this sprite:\n<sprite>\n{description}\n</sprite>"}
        ]
        total = Usage()
        for attempt in range(2):
            reply = await structured_call(
                self.client,
                self.config,
                system=system_prompt(),
                messages=messages,
                schema=OUTPUT_SCHEMA,
                role=self.role,
                on_progress=on_progress,
            )
            total = total + reply.usage
            try:
                palette = {
                    str(entry["key"]): str(entry["color"]) for entry in reply.data["palette"]
                }
                clean_palette, rows = normalize_sprite(palette, reply.data["rows"])
            except (KeyError, TypeError, PluginLoadError) as exc:
                if attempt == 1:
                    raise AgentError(f"the Artist's sprite was unusable: {exc}") from exc
                messages += [
                    {"role": "assistant", "content": reply.content},
                    {"role": "user", "content": f"That sprite is invalid: {exc}. Draw it again."},
                ]
                continue
            return sprite_source(sprite_id, clean_palette, rows), total
        raise AssertionError("unreachable")
