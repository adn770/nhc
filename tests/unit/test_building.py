"""Tests for the multi-floor Building primitive (M2, M3).

See design/building_generator.md sections 3-4.
"""

import random

import pytest

from nhc.dungeon.building import Building, StairLink
from nhc.dungeon.generators._stairs import place_cross_floor_stairs
from nhc.dungeon.model import (
    CircleShape, Level, LShape, Rect, RectShape, Terrain, Tile,
)
from nhc.hexcrawl.model import DungeonRef


def _empty_level(
    id_: str, depth: int = 1, width: int = 10, height: int = 10,
) -> Level:
    return Level.create_empty(id_, id_, depth, width, height)


def _floor_level(id_: str, depth: int, rect: Rect) -> Level:
    """Level with a rect-shaped interior carved as FLOOR."""
    level = Level.create_empty(
        id_, id_, depth, rect.x2 + 2, rect.y2 + 2,
    )
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    return level


def _two_floor_building(rect: Rect) -> Building:
    f0 = _floor_level("f0", 1, rect)
    f1 = _floor_level("f1", 2, rect)
    return Building(
        id="b", base_shape=RectShape(), base_rect=rect,
        floors=[f0, f1],
    )


class TestStairLink:
    def test_int_to_floor(self):
        link = StairLink(
            from_floor=0, to_floor=1,
            from_tile=(3, 4), to_tile=(3, 4),
        )
        assert link.from_floor == 0
        assert link.to_floor == 1
        assert link.from_tile == (3, 4)
        assert link.to_tile == (3, 4)

    def test_descent_link_with_dungeonref(self):
        ref = DungeonRef(template="procedural:crypt")
        link = StairLink(
            from_floor=0, to_floor=ref,
            from_tile=(5, 5), to_tile=(0, 0),
        )
        assert isinstance(link.to_floor, DungeonRef)
        assert link.to_floor.template == "procedural:crypt"


class TestBuilding:
    def test_minimal_building(self):
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 10, 10),
        )
        assert b.id == "b1"
        assert b.floors == []
        assert b.stair_links == []
        assert b.descent is None

    def test_default_material_and_interior(self):
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 5, 5),
        )
        assert b.wall_material == "brick"
        assert b.interior_floor == "stone"

    def test_wall_material_override(self):
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 5, 5),
            wall_material="stone",
        )
        assert b.wall_material == "stone"

    def test_interior_floor_wood(self):
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 5, 5),
            interior_floor="wood",
        )
        assert b.interior_floor == "wood"

    def test_ground_returns_first_floor(self):
        f0 = _empty_level("f0", depth=1)
        f1 = _empty_level("f1", depth=2)
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 10, 10),
            floors=[f0, f1],
        )
        assert b.ground is f0

    def test_ground_raises_when_no_floors(self):
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 10, 10),
        )
        with pytest.raises(IndexError):
            _ = b.ground

    def test_descent_ref(self):
        ref = DungeonRef(template="procedural:crypt")
        b = Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 5, 5),
            descent=ref,
        )
        assert b.descent is ref


class TestBuildingSharedPerimeter:
    def test_rect_shape_perimeter(self):
        rect = Rect(0, 0, 7, 7)
        b = Building(
            id="b1", base_shape=RectShape(), base_rect=rect,
        )
        expected = RectShape().perimeter_tiles(rect)
        assert b.shared_perimeter() == expected
        assert len(b.shared_perimeter()) > 0

    def test_circle_shape_perimeter_excludes_center(self):
        rect = Rect(0, 0, 7, 7)
        b = Building(
            id="b1", base_shape=CircleShape(), base_rect=rect,
        )
        perim = b.shared_perimeter()
        assert (3, 3) not in perim
        assert len(perim) > 0

    def test_lshape_perimeter_has_no_islands(self):
        """L-shape perimeter must form a single connected polygon."""
        rect = Rect(0, 0, 9, 9)
        b = Building(
            id="b1", base_shape=LShape(corner="nw"), base_rect=rect,
        )
        perim = b.shared_perimeter()
        assert len(perim) > 0
        start = next(iter(perim))
        visited = {start}
        stack = [start]
        while stack:
            x, y = stack.pop()
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                n = (x + dx, y + dy)
                if n in perim and n not in visited:
                    visited.add(n)
                    stack.append(n)
        assert visited == perim


class TestBuildingValidate:
    def _make(self, n_floors: int = 2) -> Building:
        floors = [
            _empty_level(f"f{i}", depth=i + 1) for i in range(n_floors)
        ]
        return Building(
            id="b1",
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 10, 10),
            floors=floors,
        )

    def test_empty_stair_links_is_valid(self):
        self._make(2).validate()

    def test_valid_adjacent_stair_links(self):
        b = self._make(3)
        b.stair_links.append(StairLink(
            from_floor=0, to_floor=1,
            from_tile=(2, 2), to_tile=(2, 2),
        ))
        b.stair_links.append(StairLink(
            from_floor=1, to_floor=2,
            from_tile=(3, 3), to_tile=(3, 3),
        ))
        b.validate()

    def test_skip_floor_rejected(self):
        b = self._make(3)
        b.stair_links.append(StairLink(
            from_floor=0, to_floor=2,
            from_tile=(2, 2), to_tile=(2, 2),
        ))
        with pytest.raises(ValueError, match="skips floors"):
            b.validate()

    def test_out_of_range_from_floor_rejected(self):
        b = self._make(2)
        b.stair_links.append(StairLink(
            from_floor=5, to_floor=6,
            from_tile=(0, 0), to_tile=(0, 0),
        ))
        with pytest.raises(ValueError, match="from_floor"):
            b.validate()

    def test_out_of_range_to_floor_rejected(self):
        b = self._make(2)
        b.stair_links.append(StairLink(
            from_floor=0, to_floor=7,
            from_tile=(0, 0), to_tile=(0, 0),
        ))
        with pytest.raises(ValueError, match="to_floor"):
            b.validate()

    def test_descent_from_ground_ok(self):
        b = self._make(2)
        ref = DungeonRef(template="procedural:crypt")
        b.stair_links.append(StairLink(
            from_floor=0, to_floor=ref,
            from_tile=(5, 5), to_tile=(0, 0),
        ))
        b.validate()

    def test_descent_from_upper_floor_rejected(self):
        b = self._make(3)
        ref = DungeonRef(template="procedural:crypt")
        b.stair_links.append(StairLink(
            from_floor=1, to_floor=ref,
            from_tile=(5, 5), to_tile=(0, 0),
        ))
        with pytest.raises(ValueError, match="ground floor"):
            b.validate()


class TestPlaceCrossFloorStairs:
    def test_single_floor_no_descent_returns_empty(self):
        rect = Rect(1, 1, 6, 6)
        b = Building(
            id="b", base_shape=RectShape(), base_rect=rect,
            floors=[_floor_level("f0", 1, rect)],
        )
        links = place_cross_floor_stairs(b, random.Random(42))
        assert links == []

    def test_two_floors_produces_one_link(self):
        b = _two_floor_building(Rect(1, 1, 6, 6))
        links = place_cross_floor_stairs(b, random.Random(42))
        assert len(links) == 1
        link = links[0]
        assert link.from_floor == 0
        assert link.to_floor == 1

    def test_stair_tiles_are_marked(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        links = place_cross_floor_stairs(b, random.Random(42))
        link = links[0]
        lower = b.floors[0]
        upper = b.floors[1]
        lx, ly = link.from_tile
        ux, uy = link.to_tile
        # Lower floor's tile is stairs_up; upper's is stairs_down.
        assert lower.tiles[ly][lx].feature == "stairs_up"
        assert upper.tiles[uy][ux].feature == "stairs_down"

    def test_aligned_tiles_across_floors(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        links = place_cross_floor_stairs(b, random.Random(42))
        for link in links:
            assert link.from_tile == link.to_tile

    def test_stair_tiles_not_on_perimeter(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        links = place_cross_floor_stairs(b, random.Random(42))
        perim = RectShape().perimeter_tiles(rect)
        for link in links:
            assert link.from_tile not in perim
            assert link.to_tile not in perim

    def test_three_floors_produces_two_adjacent_links(self):
        rect = Rect(1, 1, 6, 6)
        floors = [
            _floor_level(f"f{i}", i + 1, rect) for i in range(3)
        ]
        b = Building(
            id="b", base_shape=RectShape(), base_rect=rect,
            floors=floors,
        )
        links = place_cross_floor_stairs(b, random.Random(42))
        assert len(links) == 2
        pairs = {(link.from_floor, link.to_floor) for link in links}
        assert pairs == {(0, 1), (1, 2)}

    def test_avoids_existing_door_tiles(self):
        """Tiles with a pre-existing feature are not chosen as stairs."""
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        # Keep exactly one interior tile free on each floor; mark the
        # rest of the interior as closed doors.
        perim = RectShape().perimeter_tiles(rect)
        keep = (3, 3)
        for floor in b.floors:
            for y in range(rect.y, rect.y2):
                for x in range(rect.x, rect.x2):
                    if (x, y) in perim or (x, y) == keep:
                        continue
                    floor.tiles[y][x].feature = "door_closed"
        links = place_cross_floor_stairs(b, random.Random(42))
        assert len(links) == 1
        assert links[0].from_tile == keep

    def test_descent_adds_link_from_ground(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        ref = DungeonRef(template="procedural:crypt")
        b.descent = ref
        links = place_cross_floor_stairs(b, random.Random(42))
        # 1 internal + 1 descent
        assert len(links) == 2
        descent = [
            l for l in links if isinstance(l.to_floor, DungeonRef)
        ]
        assert len(descent) == 1
        assert descent[0].from_floor == 0
        assert descent[0].to_floor is ref
        dx, dy = descent[0].from_tile
        assert b.ground.tiles[dy][dx].feature == "stairs_down"

    def test_descent_and_upstair_use_distinct_tiles(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        b.descent = DungeonRef(template="procedural:crypt")
        links = place_cross_floor_stairs(b, random.Random(42))
        internal = next(
            l for l in links if isinstance(l.to_floor, int)
        )
        descent = next(
            l for l in links if isinstance(l.to_floor, DungeonRef)
        )
        assert internal.from_tile != descent.from_tile

    def test_links_pass_building_validate(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        b.descent = DungeonRef(template="procedural:crypt")
        b.stair_links = place_cross_floor_stairs(b, random.Random(42))
        b.validate()  # does not raise

    def test_raises_when_no_valid_shared_tile(self):
        rect = Rect(1, 1, 6, 6)
        b = _two_floor_building(rect)
        perim = RectShape().perimeter_tiles(rect)
        f0 = b.floors[0]
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                if (x, y) not in perim:
                    f0.tiles[y][x].feature = "door_closed"
        with pytest.raises(ValueError, match="no valid stair tile"):
            place_cross_floor_stairs(b, random.Random(42))

    def test_deterministic_under_same_seed(self):
        rect = Rect(1, 1, 6, 6)
        b1 = _two_floor_building(rect)
        b2 = _two_floor_building(rect)
        links1 = place_cross_floor_stairs(b1, random.Random(42))
        links2 = place_cross_floor_stairs(b2, random.Random(42))
        assert [l.from_tile for l in links1] == [
            l.from_tile for l in links2
        ]

    def test_descent_only_on_single_floor_building(self):
        """A 1-floor building with a descent still emits the descent."""
        rect = Rect(1, 1, 6, 6)
        b = Building(
            id="b", base_shape=RectShape(), base_rect=rect,
            floors=[_floor_level("f0", 1, rect)],
            descent=DungeonRef(template="procedural:crypt"),
        )
        links = place_cross_floor_stairs(b, random.Random(42))
        assert len(links) == 1
        assert isinstance(links[0].to_floor, DungeonRef)
        assert links[0].from_floor == 0
