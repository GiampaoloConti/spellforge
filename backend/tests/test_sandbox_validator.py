import textwrap

import pytest

from spellforge.plugins import BUILTIN_PLUGIN_IDS, builtin_source
from spellforge.sandbox.validator import validate_source


def problems(source: str) -> list[str]:
    return [str(p) for p in validate_source(textwrap.dedent(source))]


@pytest.mark.parametrize("plugin_id", BUILTIN_PLUGIN_IDS)
def test_builtin_plugins_pass(plugin_id):
    assert problems(builtin_source(plugin_id)) == []


def test_ordinary_python_is_allowed():
    source = """
        RADIUS = 2

        def on_cast(ctx, caster, target):
            me = ctx.entity(caster)
            hits = [e for e in ctx.entities_in_radius(target, RADIUS) if e.id != caster]
            weakest = min(hits, key=lambda e: e.hp) if hits else None
            try:
                total = sum(ctx.damage(e.id, 2, source=caster) for e in hits)
            except:
                total = 0
            match len(hits):
                case 0:
                    ctx.log("nothing")
                case n:
                    name = weakest.name if weakest else "-"
                    ctx.log(f"{me.name} hits {n} for {total}, weakest {name}")

        define_spell(id="burst", name="Burst", description="Boom.", mana_cost=3,
                     target="tile", range=5, on_cast=on_cast)
    """
    assert problems(source) == []


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ("import os", "imports are not allowed"),
        ("from spellforge.engine import game", "imports are not allowed"),
        ("x = ().__class__", "attribute `__class__` is private"),
        ("def f(ctx):\n    return ctx._game", "attribute `_game` is private"),
        ("x = __builtins__", "name `__builtins__` is not allowed"),
        ("open('secrets.txt')", "unknown name `open`"),
        ("x = getattr(1, 'real')", "unknown name `getattr`"),
        ("x = eval('1')", "unknown name `eval`"),
        ("x = '{0.__class__}'.format(1)", "str.format is not allowed"),
        ("class Sneaky:\n    pass", "classes are not allowed"),
        ("x = 1\ndef f():\n    global x", "`global` is not allowed"),
        ("async def f():\n    pass", "async code is not allowed"),
        ("def f():\n    yield 1", "generators are not allowed"),
        ("def f(p):\n    with p:\n        pass", "`with` blocks are not allowed"),
        ("def broken(:\n    pass", "line 1: syntax error"),
        ("x = 'a' * 30000", ""),  # fine: small source, big string is a runtime concern
    ],
)
def test_dangerous_constructs_are_rejected(source, fragment):
    found = problems(source)
    if fragment:
        assert any(fragment in p for p in found), found
    else:
        assert found == []


def test_problems_carry_line_numbers_and_are_deduplicated():
    source = "x = 1\nimport os\nimport sys\ny = ().__class__\n"
    assert problems(source) == [
        "line 2: imports are not allowed; everything you need is already defined",
        "line 3: imports are not allowed; everything you need is already defined",
        "line 4: attribute `__class__` is private; only public API is allowed",
    ]


def test_oversized_source_is_rejected():
    assert "longer than" in problems("x = 1\n" * 5000)[0]
