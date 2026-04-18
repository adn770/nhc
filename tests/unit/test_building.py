"""Tests for the multi-floor Building primitive (M2).

See design/building_generator.md sections 3-4.
"""

import pytest

from nhc.dungeon.building import Building, StairLink
from nhc.dungeon.model import (
    CircleShape, Level, LShape, Rect, RectShape,
)
from nhc.hexcrawl.model import DungeonRef


def _empty_level(
    id_: str, depth: int = 1, width: int = 10, height: int = 10,
) -> Level:
    return Level.create_empty(id_, id_, depth, width, height)


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
