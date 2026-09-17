"""Prompt building blocks shared by the agents.

Everything here is deterministic (no timestamps, sorted ids), so system prompts are
byte-identical across calls and prompt caching keeps working.
"""

from __future__ import annotations

from collections.abc import Iterable

from spellforge.agents.api_docs import plugin_api_reference
from spellforge.engine.game import (
    DESCEND_HEAL,
    MANA_REGEN_PER_TURN,
    PLAYER_ATTACK,
    PLAYER_MAX_HP,
    PLAYER_MAX_MANA,
)
from spellforge.plugins import builtin_source


def game_facts() -> str:
    return f"""\
- Turn-based grid roguelike. The player acts, then every monster acts, once per round.
- The dungeon is endless: clearing a level opens stairs to a deeper, harder one (the player \
heals {DESCEND_HEAL} HP and refills mana on the way down). Forged spells stay in the \
spellbook for the whole run, so they should stay useful as monsters get tougher.
- The player: {PLAYER_MAX_HP} HP, {PLAYER_ATTACK} melee damage, {PLAYER_MAX_MANA} max mana, \
+{MANA_REGEN_PER_TURN} mana per turn.
- Monsters: goblin (6 HP, 2 damage), bat (3 HP, 1 damage, erratic), skeleton archer (5 HP, \
shoots 2 damage from range), slime (10 HP, 2 damage, slow, splits into two 3 HP slimelings), \
orc brute (16 HP, 4 damage), goblin shaman (6 HP, heals other monsters).
- Built-in spells for scale: Firebolt (3 mana, 5 damage to the first creature on a line, \
range 7); Frost Nova (5 mana, cooldown 4, 2 damage + frozen for 2 turns to enemies within 2 \
tiles)."""


def capabilities() -> str:
    """What plugins can do, in design terms (for agents that don't write code)."""
    return """\
Spells and monsters are plugins built on a small API. They can:
- query creatures (position, HP, attack, faction, statuses), tiles (walls, line of sight, \
straight lines), and the seeded RNG;
- deal damage, heal, melee attack, move/teleport/push (knockback) creatures;
- apply statuses with a duration in the holder's turns: statuses can skip the holder's \
turns (stun, freeze, polymorph), run code at the start of each of its turns (damage/heal \
over time), when it takes damage (thorns, shields that heal back), when it expires, and \
when it dies (explosions, splitting); a status can also change how the holder looks;
- spawn monsters (as enemies or as allies of the player) with their own AI and sprite;
- log short messages to the player.
They cannot: change max HP, attack, mana or speed directly; change the map; make creatures \
invisible; add damage types or resistances; act outside a creature's turn except through \
status hooks. Spell targets are "self", a "tile" in range, or an "entity" in range."""


def plugin_rules() -> str:
    return f"""\
- Every id must be new: not in the list of taken ids you are given.
- Write robust code. Creatures die mid-effect, so check `ctx.entity(...)` for None before \
reading it, and re-query after actions. A "tile" target may be an empty floor tile. Loops \
over entities should use a snapshot taken before acting.
- Use only the API below. Anything else raises an error, and the plugin is disabled.
- Make it look right. When something changes how a creature looks (turned to stone, into a \
sheep, a frog, a statue; wrapped in vines; disguised) or a new creature appears (summons, \
monsters), draw a 16x16 sprite with `define_sprite` and use it through \
`define_status(appearance=...)` or `define_monster(sprite=...)`. The goblin plugin below \
shows the sprite format. Don't draw anything that isn't needed.

{plugin_api_reference()}"""


def reference_examples(names: Iterable[str] = ("firebolt", "frost_nova", "slime", "goblin")) -> str:
    plugins = "\n\n".join(
        f"### Example plugin: {name}\n```python\n{builtin_source(name).strip()}\n```"
        for name in names
    )
    return f"""\
# Reference plugins
These are real, working plugins from the game. Match their style.

{plugins}"""


def taken_ids_text(taken_ids: dict[str, list[str]]) -> str:
    return "\n".join(
        f"- {kind}: {', '.join(sorted(ids)) if ids else '(none)'}"
        for kind, ids in sorted(taken_ids.items())
    )


def feedback_prompt(problems: list[str], what: str = "plugin") -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return f"""\
Your {what} was checked in the sandbox and failed:
{listed}

Fix these problems and return the complete corrected {what} in the same JSON format."""
