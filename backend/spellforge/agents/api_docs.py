"""Builds the plugin API reference that agents read, straight from the engine's docstrings.

Generating it (instead of hand-writing a prompt) keeps the agents' documentation in sync with
the real API: change a docstring in `engine/api.py` and every agent sees the change.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable
from functools import cache
from typing import Any

from spellforge.engine.api import SAFE_BUILTINS, Ctx, EntityView, StatusView
from spellforge.engine.game import MAX_HOOK_DEPTH, MAX_OPS_PER_TURN
from spellforge.engine.geometry import Pos
from spellforge.engine.plugins import Plugin, make_namespace
from spellforge.sandbox.host import DEFAULT_CALL_TIMEOUT

FIRST_ACTION_METHOD = "damage"  # Ctx methods before this one are queries, the rest are actions


def _signature(func: Callable[..., Any], name: str, skip_self: bool = True) -> str:
    params = []
    for param in inspect.signature(func).parameters.values():
        if skip_self and param.name == "self":
            continue
        text = param.name
        if param.kind is param.KEYWORD_ONLY and not any(p.startswith("*") for p in params):
            params.append("*")
        if param.annotation is not param.empty:
            text += f": {param.annotation}"
        if param.default is not param.empty:
            text += f" = {param.default!r}"
        params.append(text)
    returns = inspect.signature(func).return_annotation
    suffix = f" -> {returns}" if returns is not inspect.Signature.empty else ""
    return f"{name}({', '.join(params)}){suffix}"


def _doc(obj: Any, indent: str = "    ") -> str:
    return textwrap.indent(inspect.getdoc(obj) or "", indent)


def _field_docs(cls: type) -> list[tuple[str, str, str]]:
    """(name, annotation, docstring) for dataclass fields, including attribute docstrings."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    body = tree.body[0].body  # type: ignore[attr-defined]
    fields = []
    for index, node in enumerate(body):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            doc = ""
            following = body[index + 1] if index + 1 < len(body) else None
            if isinstance(following, ast.Expr) and isinstance(following.value, ast.Constant):
                doc = str(following.value.value)
            fields.append((node.target.id, ast.unparse(node.annotation), doc))
    return fields


def _dataclass_section(cls: type) -> str:
    lines = [f"### {cls.__name__}", inspect.getdoc(cls) or "", ""]
    for name, annotation, doc in _field_docs(cls):
        lines.append(f"- `{name}: {annotation}`" + (f": {doc}" if doc else ""))
    for name, member in vars(cls).items():
        if isinstance(member, property):
            lines.append(
                f"- `{name}` (property)" + (f": {member.__doc__}" if member.__doc__ else "")
            )
    return "\n".join(lines)


@cache
def plugin_api_reference() -> str:
    """Markdown reference of everything plugin code can use."""
    define = make_namespace(Plugin(id="docs", source=""))
    sections = [
        "# Spellforge plugin API reference",
        "",
        "Plugins never hold live game objects: they see creatures through read-only "
        "`EntityView` snapshots, refer to them by integer id, and change the game only by "
        "calling methods on `ctx`. All randomness must come from `ctx` so games replay exactly.",
        "",
        "## Writing a plugin",
        "A plugin is one Python file. It has no imports: these names are already defined:",
        "`define_spell`, `define_status`, `define_monster`, `Pos`, `DIRECTIONS`.",
        "Available builtins (nothing else): " + ", ".join(f"`{b}`" for b in sorted(SAFE_BUILTINS)),
        "",
        "Not allowed (the file is rejected): imports, classes, `global`/`nonlocal`, "
        "generators (`yield`), `with`, async code, attributes starting with `_`, "
        "`str.format` (use f-strings), `print` (use `ctx.log`).",
        "",
        "Plugin functions run in a sandbox. Limits per turn: "
        f"{MAX_OPS_PER_TURN} ctx calls, hooks triggering hooks up to depth {MAX_HOOK_DEPTH}, "
        f"and each hook must finish within {DEFAULT_CALL_TIMEOUT:g}s. A plugin that raises an "
        "exception or misuses the API is disabled for the rest of the game.",
        "",
        "## Declaring content",
    ]
    for name in ("define_spell", "define_status", "define_monster"):
        sections += [
            f"### {_signature(define[name], name, skip_self=False)}",
            _doc(define[name]),
            "",
        ]

    sections += [
        "## Values",
        f"### Pos\n{inspect.getdoc(Pos)}",
        "",
        f"- `{_signature(Pos.distance_to, 'distance_to')}`: {inspect.getdoc(Pos.distance_to)}",
        f"- `{_signature(Pos.direction_to, 'direction_to')}`: {inspect.getdoc(Pos.direction_to)}",
        f"- `{_signature(Pos.neighbors, 'neighbors')}`: {inspect.getdoc(Pos.neighbors)}",
        "- `DIRECTIONS`: the 8 unit `Pos` steps, clockwise from north (up).",
        "",
        _dataclass_section(EntityView),
        "",
        _dataclass_section(StatusView),
        "",
        "## ctx: the game",
        inspect.getdoc(Ctx) or "",
    ]
    methods = [name for name in vars(Ctx) if name in Ctx.__abstractmethods__]
    split = methods.index(FIRST_ACTION_METHOD)
    for title, names in (("Queries", methods[:split]), ("Actions", methods[split:])):
        sections += ["", f"### {title}"]
        for name in names:
            member = getattr(Ctx, name)
            sections += [f"`ctx.{_signature(member, name)}`", _doc(member), ""]
    return "\n".join(sections).strip() + "\n"
