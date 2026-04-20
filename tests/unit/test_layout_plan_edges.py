"""LayoutPlan.interior_edges + apply_plan stamping (M2).

Partitioners emit interior walls as canonical edges via the new
field. ``apply_plan`` writes them into ``level.interior_edges``.
The legacy ``interior_walls`` tile-set still works so un-migrated
partitioners keep functioning; M4-M9 migrate them one at a time,
and M12 removes the tile-wall field entirely.
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

    def test_coexists_with_legacy_tile_walls(self) -> None:
        """Until M12, both interior_walls (tile) and interior_edges
        can be emitted by a single plan."""
        level = _empty_level()
        plan = LayoutPlan(
            rooms=[],
            interior_walls={(1, 1)},
            interior_edges={(3, 3, "north")},
        )
        apply_plan(level, plan)
        from nhc.dungeon.model import Terrain
        assert level.tiles[1][1].terrain is Terrain.WALL
        assert (3, 3, "north") in level.interior_edges


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
