"""Mutable engine-side state for creatures. Plugins only ever see `EntityView` copies."""

from __future__ import annotations

from dataclasses import dataclass, field

from spellforge.engine.api import EntityView, StatusView
from spellforge.engine.geometry import Pos


@dataclass
class StatusInstance:
    status_id: str
    remaining: int | None
    source: int | None
    armed: bool = False
    """Set at the start of the holder's turn; only armed statuses tick down at its end."""

    def view(self, holder: int) -> StatusView:
        return StatusView(self.status_id, holder, self.remaining, self.source)


@dataclass
class Entity:
    id: int
    kind: str
    name: str
    glyph: str
    faction: str
    pos: Pos
    hp: int
    max_hp: int
    attack: int
    mana: int = 0
    max_mana: int = 0
    statuses: dict[str, StatusInstance] = field(default_factory=dict)
    alive: bool = True

    def view(self) -> EntityView:
        return EntityView(
            id=self.id,
            kind=self.kind,
            name=self.name,
            glyph=self.glyph,
            faction=self.faction,
            pos=self.pos,
            hp=self.hp,
            max_hp=self.max_hp,
            mana=self.mana,
            max_mana=self.max_mana,
            attack=self.attack,
            statuses=tuple(self.statuses),
            alive=self.alive,
        )
