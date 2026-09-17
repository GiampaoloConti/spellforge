"""Hard power limits for forged spells, measured in a simulation rather than judged.

The Balancer (an LLM) reviews specs against these same numbers, but a model can be talked
round or miss a combo. So every plugin is also cast in a balance probe arena
(`verify.probe_spell`) and what it *actually did* is compared with these limits. Anything over
budget goes back to the Balancer with the measurements.

Limits depend on mana cost and cooldown: a spell may be strong if it is expensive or slow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REACH_MARGIN = 4
"""Effects may reach creatures at most this far beyond the spell's range (area around target)."""


@dataclass(frozen=True)
class SpellLimits:
    damage: int
    """Total damage to enemies from one cast (all targets, including damage over time)."""
    healing: float
    """Total healing to the player's side from one cast (including healing over time)."""
    control: int
    """Enemy turns skipped because of one cast (stuns, freezes, polymorphs...)."""
    ally_hp: int
    """Total HP of allies summoned by one cast."""
    reach: int
    """Farthest distance from the caster at which a creature may be affected."""


def spell_limits(mana_cost: int, cooldown: int, spell_range: int) -> SpellLimits:
    return SpellLimits(
        damage=3 * mana_cost + cooldown,
        healing=1.5 * mana_cost + cooldown / 2,
        control=2 * mana_cost + cooldown,
        ally_hp=2 * (4 + 2 * mana_cost),
        reach=spell_range + REACH_MARGIN,
    )


def budget_text() -> str:
    """The same limits in words, for the Balancer's prompt."""
    return f"""\
These limits are enforced by simulation: every spell is cast in a test arena and measured.
- Total damage to enemies per cast (all targets, including damage over time): at most \
3 x mana_cost + cooldown.
- Total healing to the player and allies per cast (including over time): at most \
1.5 x mana_cost + cooldown / 2. Healing must be an absolute number: no "heal to full" or \
percentage healing.
- Enemy turns skipped per cast (stun, freeze, polymorph..., counted per enemy per turn): at \
most 2 x mana_cost + cooldown.
- Allies summoned per cast: total HP at most 2 x (4 + 2 x mana_cost).
- Reach: nothing may affect creatures farther than range + {REACH_MARGIN} tiles from the \
caster. No "every enemy on the level" effects."""


@dataclass
class PowerMeasurement:
    damage: int = 0
    healing: int = 0
    control: int = 0
    ally_hp: int = 0
    farthest_reach: int = 0
    far_targets: list[str] = field(default_factory=list)

    def problems(self, limits: SpellLimits, mana_cost: int, cooldown: int) -> list[str]:
        cost = f"{mana_cost} mana, cooldown {cooldown}"
        found = []
        if self.far_targets:
            found.append(
                f"balance probe: it affected creatures {self.farthest_reach} tiles away "
                f"({', '.join(self.far_targets[:3])}); effects may reach at most "
                f"{limits.reach} tiles (range + {REACH_MARGIN}), not the whole level"
            )
        if self.damage > limits.damage:
            found.append(
                f"balance probe: one cast dealt {self.damage} damage in total; the limit for "
                f"{cost} is {limits.damage}"
            )
        if self.healing > limits.healing:
            found.append(
                f"balance probe: one cast healed {self.healing} HP (starting from 2 HP); the "
                f"limit for {cost} is {limits.healing:g}"
            )
        if self.control > limits.control:
            found.append(
                f"balance probe: one cast made enemies skip {self.control} turns; the limit "
                f"for {cost} is {limits.control}"
            )
        if self.ally_hp > limits.ally_hp:
            found.append(
                f"balance probe: one cast summoned allies with {self.ally_hp} HP in total; the "
                f"limit for {mana_cost} mana is {limits.ally_hp}"
            )
        return found
