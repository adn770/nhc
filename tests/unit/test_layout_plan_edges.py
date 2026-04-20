"""LayoutPlan.interior_edges + apply_plan stamping (M2, M12).

Partitioners emit interior walls as canonical edges via
``interior_edges``. ``apply_plan`` writes them into
``level.interior_edges``. After M12 the legacy tile-based
``interior_walls`` field is gone — partitioning is edges-only.
"""

from __future__ import annotations

import pytest

from nhc.dungeon.interior._apply import apply_plan
from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan,
)
from nhc.dungeon.model import Level, Rect, RectShape, Room


def _empty_level() -> Level:
    return Level.create_empty("t", "t", 1, 10, 10)


class TestLayoutPlanEdgesField:
    def test_defaults_to_empty_set(self) -> None:
        plan = LayoutPlan(rooms=[])
        assert plan.interior_edges == set()

    def test_field_accepts_edges(self) -> None:
        plan = LayoutPlan(
            rooms=[],
            interior_edges={(2, 3, "north"), (4, 1, "west")},
        )
        assert plan.interior_edges == {
            (2, 3, "north"), (4, 1, "west"),
        }


class TestApplyStampsEdges:
    def test_edges_land_in_level_interior_edges(self) -> None:
        level = _empty_level()
        plan = LayoutPlan(
            rooms=[],
            interior_edges={(3, 4, "north"), (5, 2, "west")},
        )
        apply_plan(level, plan)
        assert level.interior_edges == {
            (3, 4, "north"), (5, 2, "west"),
        }

    def test_apply_sets_corridor_surface_and_doors(self) -> None:
        """apply_plan also stamps corridor surface types and door
        features — edges alone do not make a layout."""
        level = _empty_level()
        plan = LayoutPlan(
            rooms=[],
            interior_edges={(3, 3, "north")},
            corridor_tiles={(5, 5)},
            doors=[InteriorDoor(
                x=5, y=6, side="north", feature="door_closed",
            )],
        )
        apply_plan(level, plan)
        from nhc.dungeon.model import SurfaceType
        assert (3, 3, "north") in level.interior_edges
        assert level.tiles[5][5].surface_type is SurfaceType.CORRIDOR
        assert level.tiles[6][5].feature == "door_closed"
        assert level.tiles[6][5].door_side == "north"


class TestEdgeInvariants:
    def test_non_canonical_edge_rejected(self) -> None:
        """apply_plan asserts every emitted edge is canonical —
        partitioners must canonicalize before returning."""
        level = _empty_level()
        plan = LayoutPlan(
            rooms=[],
            interior_edges={(3, 4, "south")},  # not canonical
        )
        with pytest.raises(AssertionError):
            apply_plan(level, plan)

    def test_doors_may_overlap_edge_runs(self) -> None:
        """A door tile at the edge position is legal: the engine
        suppresses the underlying edge via door_side. apply_plan
        must not reject this."""
        level = _empty_level()
        plan = LayoutPlan(
            rooms=[Room(
                id="r", rect=Rect(0, 0, 4, 4),
                shape=RectShape(),
            )],
            interior_edges={(2, 3, "north")},
            doors=[InteriorDoor(
                x=2, y=3, side="north", feature="door_closed",
            )],
        )
        # Should not raise.
        apply_plan(level, plan)
        assert (2, 3, "north") in level.interior_edges
