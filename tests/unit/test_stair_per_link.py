"""Per-link stair alignment tests (M5).

See ``design/building_interiors.md`` section "Stair alignment
invariant". Alignment is per-link, not per-building — a
``StairLink`` between floor N and floor N+1 reserves a single
``(x, y)`` tile shared between both floors. A middle floor in a
3+ floor building may carry two stair tiles at different coords.

``build_floors_with_stairs()`` orchestrates per-floor build +
per-link stair picking, threading the picked tile into the next
floor's partitioner as ``required_walkable``.
"""

from __future__ import annotations

import random

from nhc.dungeon.generators._stairs import build_floors_with_stairs
from nhc.dungeon.interior._floor import build_building_floor
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import Rect, RectShape, Terrain


def _floor_builder(building_id: str, base_shape, base_rect):
    """Return a build_floor_fn for a tower-like single-room build."""
    def _build(floor_idx, n_floors, required_walkable):
        return build_building_floor(
            building_id=building_id,
            floor_idx=floor_idx,
            base_shape=base_shape,
            base_rect=base_rect,
            n_floors=n_floors,
            rng=random.Random(0),
            archetype="test",
            tags=["test_interior"],
            partitioner=SingleRoomPartitioner(),
            required_walkable=required_walkable,
        )
    return _build


class TestFootprintSizedGrid:
    """A building floor allocates a footprint-sized grid anchored at the
    building's world position, not a grid sized to the world offset.

    A building far from the origin used to allocate a grid spanning
    ``(0, 0)..(base_rect.x2+2, base_rect.y2+2)`` — ~96% VOID padding.
    The footprint-sized offset grid keeps every coordinate a world
    value while shrinking the array (and its allocation cost).
    """

    def test_grid_is_footprint_sized_with_world_origin(self):
        rect = Rect(60, 72, 14, 16)  # far from the origin
        level = build_building_floor(
            building_id="b", floor_idx=0,
            base_shape=RectShape(), base_rect=rect,
            n_floors=1, rng=random.Random(0),
            archetype="test", tags=["t"],
            partitioner=SingleRoomPartitioner(),
        )
        # Footprint (14x16) + a two-tile margin (shell ring + one VOID
        # ring), not the ~76x90 a world-offset grid would allocate.
        assert (level.width, level.height) == (18, 20)
        assert (level.origin_x, level.origin_y) == (58, 70)

    def test_footprint_tiles_addressable_by_world_coord(self):
        rect = Rect(60, 72, 14, 16)
        level = build_building_floor(
            building_id="b", floor_idx=0,
            base_shape=RectShape(), base_rect=rect,
            n_floors=1, rng=random.Random(0),
            archetype="test", tags=["t"],
            partitioner=SingleRoomPartitioner(),
        )
        # Every footprint tile is FLOOR at its world coordinate, and the
        # world frame is preserved (no rebasing to local indices).
        for (wx, wy) in RectShape().floor_tiles(rect):
            tile = level.tile_at(wx, wy)
            assert tile is not None and tile.terrain is Terrain.FLOOR
        # World coords below the origin are simply out of bounds, never
        # a silent wrong-cell read.
        assert level.tile_at(0, 0) is None
        assert not level.in_bounds(0, 0)


class TestBuildFloorsWithStairs:
    def test_three_floors_produces_two_internal_stair_links(self):
        rect = Rect(1, 1, 6, 6)
        floors, links = build_floors_with_stairs(
            building_id="b",
            base_shape=RectShape(),
            base_rect=rect,
            n_floors=3,
            descent=None,
            rng=random.Random(42),
            build_floor_fn=_floor_builder("b", RectShape(), rect),
        )
        assert len(floors) == 3
        internal = [l for l in links if isinstance(l.to_floor, int)]
        assert len(internal) == 2
        pairs = {(l.from_floor, l.to_floor) for l in internal}
        assert pairs == {(0, 1), (1, 2)}

    def test_distinct_tiles_allowed_per_link(self):
        """Two links on different seeds should not be forced to share
        a coord. With many seeds, at least one must pick distinct
        tiles for the two links."""
        found_distinct = False
        for seed in range(40):
            rect = Rect(1, 1, 6, 6)
            _, links = build_floors_with_stairs(
                building_id="b",
                base_shape=RectShape(),
                base_rect=rect,
                n_floors=3,
                descent=None,
                rng=random.Random(seed),
                build_floor_fn=_floor_builder("b", RectShape(), rect),
            )
            internal = [l for l in links if isinstance(l.to_floor, int)]
            tiles = [l.from_tile for l in internal]
            if len(set(tiles)) == 2:
                found_distinct = True
                break
        assert found_distinct, (
            "no seed in 40 produced two distinct stair tiles — "
            "picker looks forced to align all links at one coord"
        )

    def test_every_link_tile_walkable_on_both_floors(self):
        rect = Rect(1, 1, 6, 6)
        floors, links = build_floors_with_stairs(
            building_id="b",
            base_shape=RectShape(),
            base_rect=rect,
            n_floors=3,
            descent=None,
            rng=random.Random(42),
            build_floor_fn=_floor_builder("b", RectShape(), rect),
        )
        for link in links:
            if not isinstance(link.to_floor, int):
                continue
            fx, fy = link.from_tile
            ux, uy = link.to_tile
            lo = floors[link.from_floor]
            hi = floors[link.to_floor]
            assert lo.tile_at(fx, fy).terrain is Terrain.FLOOR
            assert hi.tile_at(ux, uy).terrain is Terrain.FLOOR

    def test_lower_stairs_up_upper_stairs_down(self):
        rect = Rect(1, 1, 6, 6)
        floors, links = build_floors_with_stairs(
            building_id="b",
            base_shape=RectShape(),
            base_rect=rect,
            n_floors=3,
            descent=None,
            rng=random.Random(42),
            build_floor_fn=_floor_builder("b", RectShape(), rect),
        )
        for link in links:
            if not isinstance(link.to_floor, int):
                continue
            fx, fy = link.from_tile
            ux, uy = link.to_tile
            lo = floors[link.from_floor]
            hi = floors[link.to_floor]
            assert lo.tile_at(fx, fy).feature == "stairs_up"
            assert hi.tile_at(ux, uy).feature == "stairs_down"

    def test_required_walkable_threaded_to_upper_floor(self):
        """The lower floor's picked tile must appear as a walkable
        tile on the upper floor — that is what ``required_walkable``
        enforces at the partitioner boundary."""
        rect = Rect(1, 1, 6, 6)
        floors, links = build_floors_with_stairs(
            building_id="b",
            base_shape=RectShape(),
            base_rect=rect,
            n_floors=2,
            descent=None,
            rng=random.Random(42),
            build_floor_fn=_floor_builder("b", RectShape(), rect),
        )
        (link,) = [l for l in links if isinstance(l.to_floor, int)]
        tile = link.from_tile
        upper = floors[link.to_floor]
        assert upper.tile_at(tile[0], tile[1]).terrain is Terrain.FLOOR
        # stairs_down is a feature, not a blocker.
        assert upper.tile_at(tile[0], tile[1]).walkable

    def test_descent_adds_ground_floor_stairs_down(self):
        from nhc.hexcrawl.model import DungeonRef
        rect = Rect(1, 1, 6, 6)
        ref = DungeonRef(template="procedural:crypt")
        floors, links = build_floors_with_stairs(
            building_id="b",
            base_shape=RectShape(),
            base_rect=rect,
            n_floors=2,
            descent=ref,
            rng=random.Random(42),
            build_floor_fn=_floor_builder("b", RectShape(), rect),
        )
        descent_links = [
            l for l in links if isinstance(l.to_floor, DungeonRef)
        ]
        assert len(descent_links) == 1
        dlink = descent_links[0]
        assert dlink.from_floor == 0
        dx, dy = dlink.from_tile
        assert floors[0].tile_at(dx, dy).feature == "stairs_down"

    def test_single_floor_no_internal_links(self):
        rect = Rect(1, 1, 6, 6)
        floors, links = build_floors_with_stairs(
            building_id="b",
            base_shape=RectShape(),
            base_rect=rect,
            n_floors=1,
            descent=None,
            rng=random.Random(42),
            build_floor_fn=_floor_builder("b", RectShape(), rect),
        )
        assert len(floors) == 1
        assert links == []
