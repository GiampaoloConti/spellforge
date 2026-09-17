"""The structured handoffs between agents.

Agents never pass free text to each other: the Designer produces a `SpellSpec`, the Balancer
returns a `SpellReview` holding the approved spec, the Coder implements that spec, and the
Tester checks the plugin against it. The Dungeon Master path uses `MonsterSpec` and
`MonsterReview`.

Pydantic validates every agent reply. `output_schema()` derives the JSON schema sent to Claude
from the same models (structured outputs accept a subset of JSON Schema, so numeric bounds
are enforced by validation rather than by the schema).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spellforge.engine.game import PLAYER_MAX_MANA

EffectKind = Literal["damage", "heal", "status", "summon", "movement", "other"]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Effect(_Spec):
    kind: EffectKind
    summary: str = Field(max_length=200, description="One sentence: what happens, to whom.")
    amount: int = Field(
        ge=0, le=60, description="Damage/heal per hit or per turn, summon HP, etc. 0 if n/a."
    )
    duration: int = Field(ge=0, le=12, description="Turns the effect lasts. 0 if instant.")
    radius: int = Field(ge=0, le=8, description="Area radius in tiles. 0 for single target.")
    max_targets: int = Field(
        ge=0, le=20, description="Most creatures affected per cast. 0 if unlimited or n/a."
    )

    @model_validator(mode="after")
    def _absolute_amounts(self) -> Effect:
        if self.kind in ("damage", "heal") and self.amount < 1:
            raise ValueError(
                f"a {self.kind} effect needs an absolute amount (no 'full' or percentage effects)"
            )
        return self


class SpellSpec(_Spec):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(
        min_length=1, max_length=240, description="Shown to the player: what the spell does."
    )
    target: Literal["self", "tile", "entity"]
    range: int = Field(ge=0, le=12, description="Max distance to the target; 0 for self.")
    mana_cost: int = Field(ge=1, le=PLAYER_MAX_MANA)
    cooldown: int = Field(ge=0, le=20, description="Player turns between casts.")
    effects: list[Effect] = Field(min_length=1, max_length=6)
    needs_sprite: bool = Field(description="True if creatures change look or appear.")
    sprite_description: str = Field(max_length=200, description="What to draw; empty if none.")
    edge_cases: list[str] = Field(
        max_length=6, description="Situations the code must handle (empty tile, target dies...)."
    )


class Change(_Spec):
    field: str = Field(max_length=60, description='e.g. "mana_cost" or "effects[0].amount".')
    before: str = Field(max_length=60)
    after: str = Field(max_length=60)
    reason: str = Field(max_length=200)


class SpellReview(_Spec):
    verdict: Literal["approve", "adjust", "reject"]
    rationale: str = Field(max_length=300, description="1-2 sentences for the player.")
    exploits_considered: list[str] = Field(max_length=8)
    changes: list[Change] = Field(max_length=10, description="Empty unless adjusting.")
    spec: SpellSpec = Field(description="The approved spec (unchanged if approving).")


class MonsterSpec(_Spec):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=240, description="Shown to the player.")
    counters: str = Field(
        max_length=240, description="Which habit of the player this punishes, and how."
    )
    weakness: str = Field(max_length=200, description="How a player can still beat it.")
    glyph: str = Field(min_length=1, max_length=1)
    max_hp: int = Field(ge=1, le=60)
    attack: int = Field(ge=0, le=8)
    behaviour: str = Field(max_length=500, description="Turn-by-turn AI, precisely.")
    abilities: list[Effect] = Field(max_length=4)
    sprite_description: str = Field(min_length=1, max_length=200)
    taunt: str = Field(max_length=160, description="One ominous line announcing it.")


class MonsterReview(_Spec):
    verdict: Literal["approve", "adjust", "reject"]
    rationale: str = Field(max_length=300)
    exploits_considered: list[str] = Field(max_length=8)
    changes: list[Change] = Field(max_length=10)
    spec: MonsterSpec


def output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A structured-outputs JSON schema for `model`: inlined, strict, bounds removed."""
    raw = model.model_json_schema()
    definitions = raw.get("$defs", {})

    def convert(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            return convert(definitions[node["$ref"].rsplit("/", 1)[-1]])
        out: dict[str, Any] = {}
        if "enum" in node:
            out = {"type": node.get("type", "string"), "enum": node["enum"]}
        elif "const" in node:
            out = {"type": node.get("type", "string"), "enum": [node["const"]]}
        elif node.get("type") == "object":
            properties = node.get("properties", {})
            out = {
                "type": "object",
                "properties": {name: convert(prop) for name, prop in properties.items()},
                "required": list(properties),
                "additionalProperties": False,
            }
        elif node.get("type") == "array":
            out = {"type": "array", "items": convert(node["items"])}
        else:
            out = {"type": node["type"]}
        if "description" in node:
            out["description"] = node["description"]
        return out

    return convert(raw)


def spec_summary(spec: SpellSpec) -> dict[str, Any]:
    """A compact, player-facing view of a spell spec."""
    return {
        "name": spec.name,
        "description": spec.description,
        "mana_cost": spec.mana_cost,
        "cooldown": spec.cooldown,
        "effects": [effect.summary for effect in spec.effects],
        "needs_sprite": spec.needs_sprite,
    }


def _numbers_in(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+", text))


def same_numbers(a: SpellSpec, b: SpellSpec) -> bool:
    """True if two specs would lead to the same code.

    Wording may differ, but every number must match, including numbers only written in the
    prose (for example a summon's attack mentioned in an effect summary).
    """

    def key(spec: SpellSpec) -> tuple[Any, ...]:
        return (
            spec.target,
            spec.range,
            spec.mana_cost,
            spec.cooldown,
            spec.needs_sprite,
            tuple(
                (e.kind, e.amount, e.duration, e.radius, e.max_targets, _numbers_in(e.summary))
                for e in spec.effects
            ),
            _numbers_in(spec.description),
            tuple(_numbers_in(case) for case in spec.edge_cases),
        )

    return key(a) == key(b)
