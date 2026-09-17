"""Static checks on plugin source, run before any generated code executes.

This is the first layer of the sandbox. It rejects the Python features that could reach
outside the plugin API: imports, dunder and private attribute access, introspection
builtins, classes, async code and `str.format` (whose format strings can read attributes).
Every name a plugin reads must be one it defined itself, a safe builtin or part of the
plugin API.

It is deliberately strict: a legitimate spell never needs any of these features. The
subprocess runner (see `host.py`) is the second, independent layer.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from spellforge.engine.api import SAFE_BUILTINS
from spellforge.engine.plugins import PLUGIN_GLOBALS

MAX_SOURCE_CHARS = 20_000
MAX_AST_NODES = 6_000

ALLOWED_GLOBALS = frozenset(SAFE_BUILTINS) | frozenset(PLUGIN_GLOBALS)

FORBIDDEN_NODES: dict[type[ast.AST], str] = {
    ast.Import: "imports are not allowed; everything you need is already defined",
    ast.ImportFrom: "imports are not allowed; everything you need is already defined",
    ast.ClassDef: "classes are not allowed; use functions and plain data",
    ast.AsyncFunctionDef: "async code is not allowed",
    ast.Await: "async code is not allowed",
    ast.AsyncFor: "async code is not allowed",
    ast.AsyncWith: "async code is not allowed",
    ast.With: "`with` blocks are not allowed",
    ast.Global: "`global` is not allowed; keep state in the game (statuses, entities)",
    ast.Nonlocal: "`nonlocal` is not allowed",
    ast.Yield: "generators are not allowed",
    ast.YieldFrom: "generators are not allowed",
}

FORBIDDEN_ATTRIBUTES = {
    "format": "str.format is not allowed; use f-strings",
    "format_map": "str.format_map is not allowed; use f-strings",
}


@dataclass(frozen=True)
class Problem:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name the plugin itself binds anywhere (functions, args, assignments, loops...)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names.add(node.id)
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def validate_source(source: str) -> list[Problem]:
    """All static problems in `source`, or [] if it may be loaded into the sandbox."""
    if len(source) > MAX_SOURCE_CHARS:
        return [Problem(1, f"source is longer than {MAX_SOURCE_CHARS} characters")]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Problem(exc.lineno or 1, f"syntax error: {exc.msg}")]

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        return [Problem(1, "plugin is too large")]

    problems: list[Problem] = []
    allowed = ALLOWED_GLOBALS | _bound_names(tree)
    for node in nodes:
        line = getattr(node, "lineno", 1)
        for node_type, message in FORBIDDEN_NODES.items():
            if isinstance(node, node_type):
                problems.append(Problem(line, message))
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                problems.append(
                    Problem(line, f"attribute `{node.attr}` is private; only public API is allowed")
                )
            elif node.attr in FORBIDDEN_ATTRIBUTES:
                problems.append(Problem(line, FORBIDDEN_ATTRIBUTES[node.attr]))
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                problems.append(Problem(line, f"name `{node.id}` is not allowed"))
            elif isinstance(node.ctx, ast.Load) and node.id not in allowed:
                problems.append(
                    Problem(
                        line,
                        f"unknown name `{node.id}`: only your own definitions, the plugin API "
                        "and the listed builtins are available",
                    )
                )
    # Report each distinct problem once, in source order.
    return sorted(set(problems), key=lambda p: (p.line, p.message))
