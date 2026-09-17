"""The Tester: checks a plugin in the sandbox and against its approved spec.

Deterministic, no LLM. It combines the sandbox verification (`verify.py`) with spec
conformance:

- the plugin declares the spec's mana cost, cooldown, target and range;
- a sprite exists when the spec needs one;
- in the test arenas, no single hit deals more damage and no status lasts longer than the
  spec allows (catching a Coder that quietly rebalanced or misread the spec);
- monsters have the spec's HP and attack.

Its report goes back to the Coder as a list of problems.
"""

from __future__ import annotations

from spellforge.agents.specs import MonsterSpec, SpellSpec
from spellforge.agents.verify import Verification, verify_monster_source, verify_spell_source
from spellforge.engine import EventType


class Tester:
    role = "Tester"

    def test_spell(
        self, plugin_id: str, source: str, spec: SpellSpec, taken_ids: dict[str, list[str]]
    ) -> Verification:
        report = verify_spell_source(plugin_id, source, taken_ids)
        if report.spell is None:
            return report
        report.problems += spell_conformance(report, spec)
        report.ok = not report.problems
        return report

    def test_monster(
        self, plugin_id: str, source: str, spec: MonsterSpec, taken_ids: dict[str, list[str]]
    ) -> Verification:
        report = verify_monster_source(plugin_id, source, taken_ids)
        if report.monster is None:
            return report
        monster = report.monster
        if monster.max_hp != spec.max_hp:
            report.problems.append(f"spec says max_hp {spec.max_hp}, plugin has {monster.max_hp}")
        if monster.attack != spec.attack:
            report.problems.append(f"spec says attack {spec.attack}, plugin has {monster.attack}")
        if report.monster_biggest_hit > spec.attack:
            report.problems.append(
                f"in the test arena the monster dealt {report.monster_biggest_hit} damage in one "
                f"hit, but its attack is {spec.attack}; no hit may exceed its attack"
            )
        report.ok = not report.problems
        return report


def spell_conformance(report: Verification, spec: SpellSpec) -> list[str]:
    spell = report.spell
    assert spell is not None
    problems = []
    declared = {
        "mana_cost": (spec.mana_cost, spell.mana_cost),
        "cooldown": (spec.cooldown, spell.cooldown),
        "target": (spec.target, spell.target.value),
    }
    if spec.target != "self":
        declared["range"] = (spec.range, spell.range)
    for name, (wanted, actual) in declared.items():
        if wanted != actual:
            problems.append(f"spec says {name} {wanted}, but define_spell declares {actual}")
    if spec.needs_sprite and report.sprite_count == 0:
        problems.append(
            "spec needs a sprite, but the plugin defines none: draw it with define_sprite and "
            "use it via define_status(appearance=...) or define_monster(sprite=...)"
        )

    player = report.player_id
    damage_limit = max((e.amount for e in spec.effects if e.kind == "damage"), default=0)
    biggest_hit = max(
        (
            e.data["amount"]
            for e in report.events
            if e.type is EventType.DAMAGED
            and e.data.get("source") == player
            and e.data.get("target") != player
        ),
        default=0,
    )
    if biggest_hit > damage_limit:
        allowed = f"at most {damage_limit}" if damage_limit else "no damage"
        problems.append(
            f"in the test arena one hit dealt {biggest_hit} damage, but the spec allows "
            f"{allowed} per hit"
        )

    duration_limit = max((e.duration for e in spec.effects if e.duration), default=0)
    longest = max(
        (
            e.data["remaining"]
            for e in report.events
            if e.type is EventType.STATUS_APPLIED and isinstance(e.data.get("remaining"), int)
        ),
        default=0,
    )
    if duration_limit and longest > duration_limit:
        problems.append(
            f"in the test arena a status was applied for {longest} turns, but the spec's "
            f"longest duration is {duration_limit}"
        )
    return problems
