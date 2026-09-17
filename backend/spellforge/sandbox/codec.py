"""JSON encoding of the plain data that crosses the sandbox boundary.

Only the value types the plugin API uses are supported: None, bools, numbers, strings,
lists/tuples, `Pos`, `EntityView` and `StatusView`. Anything else is refused, which also
stops plugins from smuggling objects through the API.
"""

from __future__ import annotations

import math
from typing import Any

from spellforge.engine.api import EntityView, PluginError, StatusView
from spellforge.engine.geometry import Pos

MAX_DEPTH = 8
MAX_ITEMS = 1_000


def encode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise PluginError("value is nested too deeply to pass to the game")
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        # JSON has no NaN/inf; send them tagged so the receiving side can reject them.
        return value if math.isfinite(value) else {"$float": repr(value)}
    if isinstance(value, Pos):
        return {"$pos": [value.x, value.y]}
    if isinstance(value, EntityView):
        return {
            "$entity": {
                "id": value.id,
                "kind": value.kind,
                "name": value.name,
                "glyph": value.glyph,
                "faction": value.faction,
                "pos": [value.pos.x, value.pos.y],
                "hp": value.hp,
                "max_hp": value.max_hp,
                "mana": value.mana,
                "max_mana": value.max_mana,
                "attack": value.attack,
                "statuses": list(value.statuses),
                "alive": value.alive,
            }
        }
    if isinstance(value, StatusView):
        return {
            "$status": [value.status_id, value.holder, value.remaining, value.source],
        }
    if isinstance(value, list | tuple):
        if len(value) > MAX_ITEMS:
            raise PluginError(f"lists passed to the game may have at most {MAX_ITEMS} items")
        return [encode(item, depth + 1) for item in value]
    raise PluginError(f"cannot pass a {type(value).__name__} to the game API")


def decode(value: Any) -> Any:
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$pos" in value:
        x, y = value["$pos"]
        return Pos(int(x), int(y))
    if "$entity" in value:
        data = dict(value["$entity"])
        data["pos"] = Pos(*data["pos"])
        data["statuses"] = tuple(data["statuses"])
        return EntityView(**data)
    if "$status" in value:
        return StatusView(*value["$status"])
    if "$float" in value:
        return float(value["$float"])
    raise ValueError(f"unknown encoded value {value!r}")
