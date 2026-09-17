import random
from collections import deque

from spellforge.engine.gamemap import GameMap, Tile, generate_level
from spellforge.engine.geometry import DIRECTIONS, Pos, line


def test_pos_arithmetic_and_distance():
    assert Pos(2, 3) + Pos(1, -1) == Pos(3, 2)
    assert Pos(2, 3) - Pos(1, 1) == Pos(1, 2)
    assert Pos(0, 0).distance_to(Pos(3, -2)) == 3
    assert Pos(0, 0).direction_to(Pos(5, -2)) == Pos(1, -1)
    assert Pos(1, 1).direction_to(Pos(1, 1)) == Pos(0, 0)
    assert len(set(Pos(0, 0).neighbors())) == 8 == len(DIRECTIONS)


def test_line_excludes_start_includes_end():
    assert line(Pos(0, 0), Pos(3, 0)) == [Pos(1, 0), Pos(2, 0), Pos(3, 0)]
    assert line(Pos(0, 0), Pos(2, 2)) == [Pos(1, 1), Pos(2, 2)]
    assert line(Pos(1, 1), Pos(1, 1)) == []
    steep = line(Pos(0, 0), Pos(1, 4))
    assert steep[-1] == Pos(1, 4) and len(steep) == 4
    assert all(a.distance_to(b) == 1 for a, b in zip([Pos(0, 0), *steep], steep, strict=False))


def test_from_ascii_markers_and_round_trip():
    rows = [
        "#####",
        "#@.g#",
        "#..g#",
        "#####",
    ]
    game_map, markers = GameMap.from_ascii(rows)
    assert markers == {"@": [Pos(1, 1)], "g": [Pos(3, 1), Pos(3, 2)]}
    assert game_map.to_ascii() == ["#####", "#...#", "#...#", "#####"]
    assert game_map.is_wall(Pos(0, 0)) and not game_map.is_wall(Pos(1, 1))
    assert game_map.is_wall(Pos(-1, 2)) and game_map.is_wall(Pos(5, 1))


def test_line_of_sight_blocked_by_walls():
    game_map, _ = GameMap.from_ascii(
        [
            ".....",
            "..#..",
            ".....",
        ]
    )
    assert not game_map.has_line_of_sight(Pos(0, 1), Pos(4, 1))
    assert game_map.has_line_of_sight(Pos(0, 0), Pos(4, 0))
    # The endpoint itself may be a wall (you can see a wall).
    assert game_map.has_line_of_sight(Pos(0, 1), Pos(2, 1))


def test_generate_level_is_deterministic_and_connected():
    a = generate_level(random.Random(7))
    b = generate_level(random.Random(7))
    c = generate_level(random.Random(8))
    assert a.map.to_ascii() == b.map.to_ascii()
    assert a.map.to_ascii() != c.map.to_ascii()
    assert len(a.rooms) >= 2

    floors = {
        Pos(x, y)
        for y in range(a.map.height)
        for x in range(a.map.width)
        if a.map.tiles[y][x] is Tile.FLOOR
    }
    start = a.rooms[0].center
    seen, queue = {start}, deque([start])
    while queue:
        for nxt in queue.popleft().neighbors():
            if nxt in floors and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert seen == floors
