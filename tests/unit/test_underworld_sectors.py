"""Tests for underworld sector mapping.

The underworld floor is shared by every cluster member. Each
floor tile is assigned to the nearest member's stairs_up so the
game can tell which surface hex the player is "under" at any
moment.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.underworld import assign_sector_map


def _carve(level: Level, x: int, y: int) -> None:
    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)


def _make_level(width: int = 20, height: int = 10) -> Level:
    return Level.create_empty(
        id="test", name="Test", depth=2,
        width=width, height=height,
    )


class TestAssignSectorMap:
    def test_empty_stairs_returns_empty_map(self):
        level = _make_level()
        _carve(level, 5, 5)
        result = assign_sector_map(level, {})
        assert result == {}

    def test_single_member_claims_all_floor_tiles(self):
        level = _make_level()
        _carve(level, 2, 2)
        _carve(level, 10, 5)
        stairs = {HexCoord(0, 0): (2, 2)}
        result = assign_sector_map(level, stairs)
        assert result[(2, 2)] == HexCoord(0, 0)
        assert result[(10, 5)] == HexCoord(0, 0)

    def test_two_members_split_by_proximity(self):
        level = _make_level(20, 10)
        # Floor across the middle row
        for x in range(20):
            _carve(level, x, 5)
        stairs = {
            HexCoord(0, 0): (2, 5),
            HexCoord(1, 0): (17, 5),
        }
        result = assign_sector_map(level, stairs)
        # Tile right next to A's stairs → A
        assert result[(3, 5)] == HexCoord(0, 0)
        # Tile right next to B's stairs → B
        assert result[(16, 5)] == HexCoord(1, 0)
        # Midpoint: closer to A (distance 7) vs B (distance 8) → A
        assert result[(9, 5)] == HexCoord(0, 0)
        assert result[(10, 5)] == HexCoord(1, 0)

    def test_ignores_non_floor_tiles(self):
        level = _make_level()
        _carve(level, 5, 5)
        # Leave the rest as VOID
        stairs = {HexCoord(0, 0): (5, 5)}
        result = assign_sector_map(level, stairs)
        assert (5, 5) in result
        # VOID tiles should not appear
        assert (0, 0) not in result
        assert (19, 9) not in result

    def test_tile_counts_match_coverage(self):
        level = _make_level()
        for x in range(20):
            for y in range(10):
                _carve(level, x, y)
        stairs = {
            HexCoord(0, 0): (5, 5),
            HexCoord(1, 0): (15, 5),
        }
        result = assign_sector_map(level, stairs)
        # Every floor tile should be in the map
        assert len(result) == 20 * 10
        # Values drawn from the provided members
        values = set(result.values())
        assert values == {HexCoord(0, 0), HexCoord(1, 0)}
