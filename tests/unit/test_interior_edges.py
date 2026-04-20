"""Edge-wall primitive on Level (M1).

Interior partitioning walls live on tile edges, not on tiles.
``canonicalize`` normalizes every ``(x, y, side)`` triple to a
canonical form with ``side ∈ {"north", "west"}`` so the set
contains one entry per physical edge. ``edge_between(a, b)``
returns the canonical edge crossed when stepping from ``a`` to
``b``.
"""

from __future__ import annotations

import pytest

from nhc.dungeon.model import (
    Level, Terrain, Tile, canonicalize, edge_between,
)


class TestCanonicalize:
    def test_north_is_canonical(self) -> None:
        assert canonicalize(3, 5, "north") == (3, 5, "north")

    def test_west_is_canonical(self) -> None:
        assert canonicalize(3, 5, "west") == (3, 5, "west")

    def test_south_maps_to_north_of_neighbor(self) -> None:
        # South edge of (3, 5) == north edge of (3, 6).
        assert canonicalize(3, 5, "south") == (3, 6, "north")

    def test_east_maps_to_west_of_neighbor(self) -> None:
        # East edge of (3, 5) == west edge of (4, 5).
        assert canonicalize(3, 5, "east") == (4, 5, "west")

    def test_idempotent(self) -> None:
        for side in ("north", "south", "east", "west"):
            c = canonicalize(4, 7, side)
            assert canonicalize(*c) == c

    def test_rejects_unknown_side(self) -> None:
        with pytest.raises(ValueError):
            canonicalize(1, 1, "up")


class TestEdgeBetween:
    def test_south_step(self) -> None:
        # Step from (3, 2) to (3, 3) crosses the north edge of (3, 3).
        assert edge_between((3, 2), (3, 3)) == (3, 3, "north")

    def test_north_step(self) -> None:
        assert edge_between((3, 3), (3, 2)) == (3, 3, "north")

    def test_east_step(self) -> None:
        assert edge_between((3, 2), (4, 2)) == (4, 2, "west")

    def test_west_step(self) -> None:
        assert edge_between((4, 2), (3, 2)) == (4, 2, "west")

    def test_symmetric(self) -> None:
        assert edge_between((2, 2), (2, 3)) == edge_between((2, 3), (2, 2))
        assert edge_between((2, 2), (3, 2)) == edge_between((3, 2), (2, 2))

    def test_rejects_non_orthogonal(self) -> None:
        with pytest.raises(ValueError):
            edge_between((2, 2), (3, 3))

    def test_rejects_same_tile(self) -> None:
        with pytest.raises(ValueError):
            edge_between((2, 2), (2, 2))


class TestLevelInteriorEdgesDefault:
    def test_empty_level_has_no_edges(self) -> None:
        level = Level.create_empty("l", "L", 1, 5, 5)
        assert level.interior_edges == set()

    def test_edges_field_is_set(self) -> None:
        level = Level.create_empty("l", "L", 1, 5, 5)
        level.interior_edges.add((2, 2, "north"))
        assert (2, 2, "north") in level.interior_edges


class TestSaveRoundTrip:
    def test_interior_edges_survive_save_load(self) -> None:
        from nhc.core.save import _deserialize_level, _serialize_level

        level = Level.create_empty("l", "L", 1, 4, 4)
        # Make a couple of tiles FLOOR so the level isn't trivially
        # empty.
        level.tiles[1][1] = Tile(terrain=Terrain.FLOOR)
        level.tiles[1][2] = Tile(terrain=Terrain.FLOOR)
        level.interior_edges.update({
            (1, 2, "north"),
            (2, 1, "west"),
        })

        data = _serialize_level(level)
        loaded = _deserialize_level(data)

        assert loaded.interior_edges == level.interior_edges

    def test_old_saves_without_edges_default_empty(self) -> None:
        """A save serialized before this field existed must still
        load — missing ``interior_edges`` defaults to empty set."""
        from nhc.core.save import _deserialize_level, _serialize_level

        level = Level.create_empty("l", "L", 1, 3, 3)
        data = _serialize_level(level)
        # Simulate an older save by dropping the field from the
        # serialized dict (before sending it back through the
        # loader).
        data.pop("interior_edges", None)
        loaded = _deserialize_level(data)
        assert loaded.interior_edges == set()
