"""Grid geometry: positions, directions, distances and lines.

Everything here is pure and deterministic. `Pos` and `DIRECTIONS` are part of the
plugin API, so the docstrings are written for plugin authors (human or agent).
"""

from __future__ import annotations

from dataclasses import dataclass


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


@dataclass(frozen=True, slots=True)
class Pos:
    """A tile coordinate on the grid. `x` grows to the right, `y` grows downward.

    Positions are immutable values: `Pos(2, 3) == Pos(2, 3)`. You can add and subtract
    them: `Pos(2, 3) + Pos(1, 0) == Pos(3, 3)`.
    """

    x: int
    y: int

    def __add__(self, other: Pos) -> Pos:
        return Pos(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Pos) -> Pos:
        return Pos(self.x - other.x, self.y - other.y)

    def distance_to(self, other: Pos) -> int:
        """Number of king-moves between two tiles (diagonal steps count as 1)."""
        return max(abs(self.x - other.x), abs(self.y - other.y))

    def direction_to(self, other: Pos) -> Pos:
        """Unit step (each axis -1, 0 or 1) pointing from this tile toward `other`.

        Returns `Pos(0, 0)` when both tiles are the same.
        """
        return Pos(_sign(other.x - self.x), _sign(other.y - self.y))

    def neighbors(self) -> list[Pos]:
        """The 8 surrounding tiles, in the same order as `DIRECTIONS`.

        Tiles may be out of bounds or walls: check with `ctx.is_walkable`.
        """
        return [self + d for d in DIRECTIONS]


DIRECTIONS: tuple[Pos, ...] = (
    Pos(0, -1),
    Pos(1, -1),
    Pos(1, 0),
    Pos(1, 1),
    Pos(0, 1),
    Pos(-1, 1),
    Pos(-1, 0),
    Pos(-1, -1),
)
"""The 8 unit directions, clockwise starting from north (up)."""


def line(start: Pos, end: Pos) -> list[Pos]:
    """Tiles on a straight Bresenham line from `start` (excluded) to `end` (included)."""
    points: list[Pos] = []
    x0, y0 = start.x, start.y
    dx, dy = abs(end.x - x0), -abs(end.y - y0)
    sx, sy = _sign(end.x - x0), _sign(end.y - y0)
    err = dx + dy
    while (x0, y0) != (end.x, end.y):
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
        points.append(Pos(x0, y0))
    return points
