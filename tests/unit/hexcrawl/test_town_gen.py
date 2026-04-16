"""Settlement town-map generator.

The generator emits a small single-floor :class:`Level` with five
named building rooms (shop, temple, inn, stable, training) and a
central entry tile. Generated on demand by
``Game.enter_hex_feature`` when the player steps onto a CITY or
VILLAGE hex (wiring lands in M-2.3).
"""

from __future__ import annotations

from collections import deque

import pytest

from nhc.dungeon.model import Terrain
from nhc.hexcrawl.town import REQUIRED_BUILDINGS, generate_town


# ---------------------------------------------------------------------------
# Required buildings
# ---------------------------------------------------------------------------


def test_town_generator_emits_level() -> None:
    level = generate_town(seed=1)
    assert level.width > 0
    assert level.height > 0
    assert len(level.rooms) >= len(REQUIRED_BUILDINGS)


def test_town_generator_places_required_buildings() -> None:
    level = generate_town(seed=1)
    tags = {t for room in level.rooms for t in room.tags}
    for building in REQUIRED_BUILDINGS:
        assert building in tags, (
            f"town generator should produce a '{building}' room, "
            f"got tags={tags}"
        )


def test_town_generator_distinct_rooms_per_building() -> None:
    level = generate_town(seed=1)
    # Each of the five buildings belongs to its own distinct room.
    by_building: dict[str, list[str]] = {b: [] for b in REQUIRED_BUILDINGS}
    for room in level.rooms:
        for t in room.tags:
            if t in by_building:
                by_building[t].append(room.id)
    for building, rooms in by_building.items():
        assert len(rooms) == 1, (
            f"building {building!r} appears in {len(rooms)} rooms: {rooms}"
        )


# ---------------------------------------------------------------------------
# Seed reproducibility
# ---------------------------------------------------------------------------


def test_town_generator_seed_reproducibility() -> None:
    a = generate_town(seed=42)
    b = generate_town(seed=42)
    assert a.width == b.width
    assert a.height == b.height
    assert len(a.rooms) == len(b.rooms)
    # Tag layout is identical.
    tags_a = sorted((r.id, tuple(r.tags)) for r in a.rooms)
    tags_b = sorted((r.id, tuple(r.tags)) for r in b.rooms)
    assert tags_a == tags_b
    # Tile terrain is identical.
    for y in range(a.height):
        for x in range(a.width):
            assert a.tile_at(x, y).terrain == b.tile_at(x, y).terrain


def test_town_generator_different_seeds_reshuffle_buildings() -> None:
    # Geometry is deterministic across seeds (the five slot rects
    # don't move), but *which* building occupies which slot is
    # seed-driven. Assert at least one slot's tag changes.
    def tag_map(level):
        return {r.id: tuple(r.tags) for r in level.rooms}
    a = tag_map(generate_town(seed=1))
    b = tag_map(generate_town(seed=17))
    assert a != b, "different seeds should shuffle building slots"


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


def _walkable_neighbors(level, x, y):
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if not (0 <= nx < level.width and 0 <= ny < level.height):
            continue
        tile = level.tile_at(nx, ny)
        if tile is None:
            continue
        if tile.terrain is Terrain.FLOOR:
            yield (nx, ny)


def _find_entry(level) -> tuple[int, int]:
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tile_at(x, y)
            if tile and tile.feature == "stairs_up":
                return (x, y)
    raise AssertionError("town should have a stairs_up entry tile")


def test_town_has_entry_tile() -> None:
    level = generate_town(seed=1)
    entry = _find_entry(level)
    ex, ey = entry
    assert 0 <= ex < level.width
    assert 0 <= ey < level.height
    assert level.tile_at(ex, ey).terrain == Terrain.FLOOR


def test_town_buildings_reachable_from_entry() -> None:
    level = generate_town(seed=7)
    entry = _find_entry(level)
    # BFS over walkable neighbours.
    seen = {entry}
    frontier: deque[tuple[int, int]] = deque([entry])
    while frontier:
        cur = frontier.popleft()
        for n in _walkable_neighbors(level, *cur):
            if n in seen:
                continue
            seen.add(n)
            frontier.append(n)
    # Every building room must have at least one floor tile
    # reachable from the entry.
    by_tag = {t: r for r in level.rooms for t in r.tags
              if t in REQUIRED_BUILDINGS}
    for building, room in by_tag.items():
        room_floor = room.floor_tiles()
        assert any(t in seen for t in room_floor), (
            f"{building!r} room has no tile reachable from entry"
        )
