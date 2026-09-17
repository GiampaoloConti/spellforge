"""Turns engine events into short human-readable log lines, for any client."""

from __future__ import annotations

from spellforge.engine import Event, EventType, Game


class Narrator:
    """Remembers entity names, so it can still describe creatures after they die."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self.names: dict[int, str] = {}
        self._remember()

    def narrate(self, events: list[Event]) -> list[str]:
        lines = []
        for event in events:
            if event.type is EventType.SPAWNED:
                spawned = self.game.entities.get(event.data["entity"])
                self.names[event.data["entity"]] = spawned.name if spawned else event.data["kind"]
            text = describe(event, self.names, self.game.player.id)
            if text:
                lines.append(text)
        self._remember()
        return lines

    def _remember(self) -> None:
        self.names.update({e.id: e.name for e in self.game.entities.values()})


def describe(event: Event, names: dict[int, str], player_id: int) -> str | None:
    d = event.data

    def who(entity_id: int | None, verb: str, plural: str | None = None) -> str:
        """Subject + verb with agreement: "You attack" / "The goblin attacks"."""
        if entity_id == player_id:
            return f"You {verb}"
        name = names.get(entity_id, "something") if entity_id is not None else "something"
        return f"The {name} {plural or verb + 's'}"

    def whom(entity_id: int) -> str:
        return "you" if entity_id == player_id else f"the {names.get(entity_id, 'something')}"

    match event.type:
        case EventType.ATTACKED:
            return f"{who(d['attacker'], 'attack')} {whom(d['target'])}."
        case EventType.DAMAGED:
            return f"{who(d['target'], 'take')} {d['amount']} damage ({d['hp']} HP left)."
        case EventType.HEALED:
            return f"{who(d['target'], 'heal')} {d['amount']} HP."
        case EventType.DIED:
            return f"{who(d['entity'], 'die')}!"
        case EventType.SPAWNED:
            return f"A {d['kind']} appears."
        case EventType.STATUS_APPLIED if not d["refreshed"]:
            return f"{who(d['entity'], 'are', 'is')} now {d['status']}."
        case EventType.STATUS_EXPIRED | EventType.STATUS_REMOVED:
            return f"{who(d['entity'], 'are', 'is')} no longer {d['status']}."
        case EventType.SPELL_CAST:
            return f"{who(d['caster'], 'cast')} {d['spell']}."
        case EventType.MESSAGE:
            return str(d["text"])
        case EventType.PLUGIN_DISABLED:
            return f"!! The arcane forge rejected '{d['plugin']}': {d['reason']}"
        case EventType.GAME_OVER:
            return "*** You win! ***" if d["result"] == "won" else "*** You died. ***"
    return None
