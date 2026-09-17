"""The sandbox worker: a separate process that loads and runs exactly one plugin.

Started by `host.PluginSandbox`. It talks JSON lines over stdin/stdout:

    host -> worker  {"op": "load", "plugin_id": ..., "source": ...}
    worker -> host  {"op": "loaded", "spells": [...], ...} | {"op": "load_error", ...}
    host -> worker  {"op": "call", "key": "spell:firebolt:on_cast", "args": [...]}
    worker -> host  {"op": "ctx", "method": "damage", "args": [...], "kwargs": {...}}
    host -> worker  {"op": "result", "value": ...} | {"op": "ctx_error", "message": ...}
    worker -> host  {"op": "return"} | {"op": "error", "message": ...}

While a hook waits for a ctx result, the host may send a nested "call" (for example the
spell's own status reacting to damage it just dealt); the worker handles it recursively.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, NoReturn

from spellforge.engine.api import Ctx, PluginError
from spellforge.engine.plugins import Plugin, PluginLoadError, load_plugin
from spellforge.sandbox.codec import decode, encode
from spellforge.sandbox.hardening import restrict_worker
from spellforge.sandbox.validator import validate_source

CTX_METHODS = frozenset(Ctx.__abstractmethods__)
STATUS_HOOKS = ("on_apply", "on_turn", "on_expire", "on_damaged", "on_death")
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


class Channel:
    def __init__(self) -> None:
        self._in = sys.stdin.buffer
        self._out = sys.stdout.buffer

    def send(self, message: dict[str, Any]) -> None:
        self._out.write(json.dumps(message).encode() + b"\n")
        self._out.flush()

    def receive(self) -> dict[str, Any]:
        line = self._in.readline()
        if not line:
            sys.exit(0)  # host went away
        return json.loads(line)


class Worker:
    def __init__(self, channel: Channel) -> None:
        self.channel = channel
        self.hooks: dict[str, Callable[..., Any]] = {}
        self.ctx = RemoteCtx(self)

    # ---- loading -------------------------------------------------------------

    def load(self, plugin_id: str, source: str) -> None:
        problems = validate_source(source)
        if problems:
            self.channel.send({"op": "load_error", "message": "; ".join(map(str, problems))})
            return
        try:
            plugin = load_plugin(plugin_id, source)
        except PluginLoadError as exc:
            self.channel.send({"op": "load_error", "message": str(exc)})
            return
        self.channel.send({"op": "loaded", **self._describe(plugin)})

    def _describe(self, plugin: Plugin) -> dict[str, Any]:
        spells = []
        for spell in plugin.spells:
            self.hooks[f"spell:{spell.id}:on_cast"] = spell.on_cast
            spells.append(
                {
                    "id": spell.id,
                    "name": spell.name,
                    "description": spell.description,
                    "mana_cost": spell.mana_cost,
                    "cooldown": spell.cooldown,
                    "target": spell.target.value,
                    "range": spell.range,
                    "requires_line_of_sight": spell.requires_line_of_sight,
                }
            )
        statuses = []
        for status in plugin.statuses:
            hooks = [name for name in STATUS_HOOKS if getattr(status, name) is not None]
            for name in hooks:
                self.hooks[f"status:{status.id}:{name}"] = getattr(status, name)
            statuses.append(
                {
                    "id": status.id,
                    "name": status.name,
                    "description": status.description,
                    "prevents_action": status.prevents_action,
                    "appearance": status.appearance,
                    "hooks": hooks,
                }
            )
        monsters = []
        for monster in plugin.monsters:
            if monster.act is not None:
                self.hooks[f"monster:{monster.id}:act"] = monster.act
            monsters.append(
                {
                    "id": monster.id,
                    "name": monster.name,
                    "description": monster.description,
                    "glyph": monster.glyph,
                    "max_hp": monster.max_hp,
                    "attack": monster.attack,
                    "sprite": monster.sprite,
                    "has_act": monster.act is not None,
                }
            )
        sprites = [
            {"id": sprite.id, "palette": sprite.palette, "rows": list(sprite.rows)}
            for sprite in plugin.sprites
        ]
        return {"spells": spells, "statuses": statuses, "monsters": monsters, "sprites": sprites}

    # ---- running hooks ---------------------------------------------------------

    def run_call(self, message: dict[str, Any]) -> None:
        hook = self.hooks.get(message["key"])
        if hook is None:
            self.channel.send({"op": "error", "message": f"unknown hook {message['key']}"})
            return
        try:
            hook(self.ctx, *decode(message["args"]))
        except BaseException as exc:  # noqa: BLE001 - report everything, including SystemExit
            self.channel.send({"op": "error", "message": f"{type(exc).__name__}: {exc}"})
            return
        self.channel.send({"op": "return"})

    def call_ctx(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        self.channel.send(
            {"op": "ctx", "method": method, "args": encode(args), "kwargs": encode_kwargs(kwargs)}
        )
        while True:
            message = self.channel.receive()
            match message["op"]:
                case "result":
                    return decode(message["value"])
                case "ctx_error":
                    raise PluginError(message["message"])
                case "call":
                    self.run_call(message)  # nested hook while we wait
                case other:
                    fail(f"unexpected message while waiting for ctx result: {other}")


def encode_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: encode(value) for key, value in kwargs.items()}


class RemoteCtx(Ctx):
    """Implements every `Ctx` method by asking the host process to run it."""

    def __init__(self, worker: Worker) -> None:
        self._worker = worker


def _remote_method(name: str) -> Callable[..., Any]:
    def method(self: RemoteCtx, *args: Any, **kwargs: Any) -> Any:
        return self._worker.call_ctx(name, args, kwargs)

    method.__name__ = name
    method.__doc__ = getattr(Ctx, name).__doc__
    return method


for _name in CTX_METHODS:
    setattr(RemoteCtx, _name, _remote_method(_name))
RemoteCtx.__abstractmethods__ = frozenset()


def fail(message: str) -> NoReturn:
    sys.stderr.write(message + "\n")
    sys.exit(2)


def main() -> None:
    restrict_worker(MEMORY_LIMIT_BYTES)
    channel = Channel()
    worker = Worker(channel)
    while True:
        message = channel.receive()
        match message["op"]:
            case "load":
                worker.load(message["plugin_id"], message["source"])
            case "call":
                worker.run_call(message)
            case "exit":
                return
            case other:
                fail(f"unexpected message {other}")


if __name__ == "__main__":
    main()
