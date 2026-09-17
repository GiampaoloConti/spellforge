"""The tile map: walls and floors, plus a seeded rooms-and-corridors generator."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from spellforge.engine.geometry import Pos, line


class Tile(StrEnum):
    FLOOR = "."
    WALL = "#"


@dataclass
class GameMap:
    width: int
    height: int
    tiles: list[list[Tile]]  # indexed tiles[y][x]

    @classmethod
    def filled(cls, width: int, height: int, tile: Tile = Tile.WALL) -> GameMap:
        return cls(width, height, [[tile] * width for _ in range(height)])

    @classmethod
    def from_ascii(cls, rows: list[str]) -> tuple[GameMap, dict[str, list[Pos]]]:
        """Parse an ASCII map. `#` is a wall; every other character is floor.

        Characters other than `#` and `.` are returned as markers (char -> positions in
        reading order), so tests can place entities with e.g. `@` and `g`.
        """
        if not rows or any(len(r) != len(rows[0]) for r in rows):
            raise ValueError("ASCII map rows must be non-empty and equally long")
        game_map = cls.filled(len(rows[0]), len(rows), Tile.FLOOR)
        markers: dict[str, list[Pos]] = {}
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == Tile.WALL:
                    game_map.tiles[y][x] = Tile.WALL
                elif ch != Tile.FLOOR:
                    markers.setdefault(ch, []).append(Pos(x, y))
        return game_map, markers

    def to_ascii(self) -> list[str]:
        return ["".join(row) for row in self.tiles]

    def in_bounds(self, pos: Pos) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def is_wall(self, pos: Pos) -> bool:
        """Out-of-bounds tiles count as walls."""
        return not self.in_bounds(pos) or self.tiles[pos.y][pos.x] is Tile.WALL

    def set(self, pos: Pos, tile: Tile) -> None:
        self.tiles[pos.y][pos.x] = tile

    def has_line_of_sight(self, start: Pos, end: Pos) -> bool:
        """True if no wall lies strictly between `start` and `end`."""
        return not any(self.is_wall(p) for p in line(start, end)[:-1])


@dataclass(frozen=True)
class Room:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Pos:
        return Pos(self.x + self.w // 2, self.y + self.h // 2)

    def floor_tiles(self) -> list[Pos]:
        return [
            Pos(x, y)
            for y in range(self.y, self.y + self.h)
            for x in range(self.x, self.x + self.w)
        ]

    def intersects(self, other: Room, margin: int = 1) -> bool:
        return (
            self.x - margin < other.x + other.w
            and other.x - margin < self.x + self.w
            and self.y - margin < other.y + other.h
            and other.y - margin < self.y + self.h
        )


@dataclass
class GeneratedLevel:
    map: GameMap
    rooms: list[Room] = field(default_factory=list)


def generate_level(
    rng: random.Random,
    width: int = 48,
    height: int = 20,
    max_rooms: int = 8,
    min_size: int = 4,
    max_size: int = 9,
) -> GeneratedLevel:
    """Carve non-overlapping rooms and join each to the previous one with an L corridor.

    Because every room connects to its predecessor, all floor tiles are reachable.
    """
    game_map = GameMap.filled(width, height)
    rooms: list[Room] = []
    for _ in range(max_rooms * 5):
        if len(rooms) >= max_rooms:
            break
        w = rng.randint(min_size, max_size)
        h = rng.randint(min_size, min(max_size, height - 2))
        room = Room(rng.randint(1, width - w - 1), rng.randint(1, height - h - 1), w, h)
        if any(room.intersects(other) for other in rooms):
            continue
        for pos in room.floor_tiles():
            game_map.set(pos, Tile.FLOOR)
        if rooms:
            _carve_corridor(
                game_map, rooms[-1].center, room.center, horizontal_first=rng.random() < 0.5
            )
        rooms.append(room)
    return GeneratedLevel(game_map, rooms)


def _carve_corridor(game_map: GameMap, a: Pos, b: Pos, horizontal_first: bool) -> None:
    corner = Pos(b.x, a.y) if horizontal_first else Pos(a.x, b.y)
    for segment_start, segment_end in ((a, corner), (corner, b)):
        game_map.set(segment_start, Tile.FLOOR)
        for pos in line(segment_start, segment_end):
            game_map.set(pos, Tile.FLOOR)
