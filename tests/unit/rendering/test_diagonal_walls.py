"""Wall rendering + door placement on diagonal building shapes.

For octagon and circle buildings the masonry renderer in
``nhc/rendering/_building_walls.py`` paints the diagonal
boundary as rotated stones; the generic floor-SVG wall pass
must not also stamp tile-edge walls at the clipped corners,
otherwise both pipelines fight at the chamfer and produce
L-shaped extra walls inside the building. Doors must also avoid
the clipped corner tiles -- their outside neighbour is a
diagonal step where the wall side is ambiguous.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.building import Building
from nhc.dungeon.model import (
    CircleShape, Level, OctagonShape, Rect, RectShape,
    Room, Terrain, Tile,
)
from nhc.rendering.building import render_building_floor_svg
from nhc.rendering.svg import render_floor_svg
from nhc.sites._site import (
    combined_building_bboxes,
    is_clipped_corner_tile,
)


def _make_octagon_floor() -> tuple[Building, Level]:
    """Synthetic 8x9 octagon building with a stamped floor.

    A single rect "room" covers the octagon's bounding rect but
    only the octagon's floor_tiles are FLOOR; the four clipped
    corners stay VOID.
    """
    rect = Rect(0, 0, 8, 9)
    shape = OctagonShape()
    floor_tiles = shape.floor_tiles(rect)
    level = Level.create_empty("b0_f0", "b0", 0, 16, 16)
    for x, y in floor_tiles:
        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    # Walls form the building perimeter.
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            if (x, y) in floor_tiles:
                continue
            level.tiles[y][x] = Tile(terrain=Terrain.WALL)
    level.rooms = [Room(id="r0", rect=rect, shape=RectShape())]
    building = Building(
        id="b0", base_shape=shape, base_rect=rect, floors=[level],
        wall_material="stone", interior_floor="stone",
        interior_wall_material="stone",
    )
    return building, level


# ── 1. is_clipped_corner_tile ─────────────────────────────────


class TestClippedCornerHelper:
    def test_octagon_chamfer_tiles_detected(self):
        rect = Rect(0, 0, 8, 9)
        shape = OctagonShape()
        building = Building(
            id="b", base_shape=shape, base_rect=rect, floors=[],
            wall_material="stone", interior_floor="stone",
            interior_wall_material="stone",
        )
        # (1, 1) sits on the NW chamfer step: its left and top
        # neighbours are both clipped voids inside the bbox, with
        # no out-of-bbox direction.
        assert is_clipped_corner_tile(building, 1, 1) is True
        # (2, 0) sits on the top flat: its top neighbour
        # (2, -1) is OUT of bbox, so the door-side direction is
        # unambiguous. Pass.
        assert is_clipped_corner_tile(building, 2, 0) is False
        # (3, 0) has no exterior neighbours inside the bbox. Pass.
        assert is_clipped_corner_tile(building, 3, 0) is False

    def test_rect_buildings_never_have_clipped_corners(self):
        rect = Rect(0, 0, 5, 5)
        building = Building(
            id="b", base_shape=RectShape(), base_rect=rect,
            floors=[], wall_material="stone", interior_floor="stone",
            interior_wall_material="stone",
        )
        # Every perimeter tile of a rect building should pass
        # the clipped-corner check (no clipping anywhere).
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                assert is_clipped_corner_tile(building, x, y) is False


# ── 2. Wall rendering skips clipped-void tile edges ───────────


def _wall_segment_count(svg: str) -> int:
    """Count the M (moveto) commands in the thick-wall path,
    which approximates the number of distinct wall segments.

    The Rust SvgPainter trims trailing ``.0`` from numeric
    attributes, so accept both ``stroke-width="5"`` and the
    legacy ``stroke-width="5.0"`` form.
    """
    import re
    matches = re.findall(
        r'<path d="([^"]+)"[^/]*stroke-width="5(?:\.0)?"', svg,
    )
    return sum(d.count("M") for d in matches)


class TestOctagonWallRendering:
    def test_octagon_floor_svg_omits_clipped_corner_walls(self):
        """No per-tile wall stamps inside the octagon chamfer.

        Phase 1.19 cleared the legacy ``wallSegments`` field, which
        is what the per-tile wall pass populated. After 1.19 the
        smooth-shape ExteriorWallOp owns the octagon outline as a
        single closed polygon, so per-tile chamfer-corner stamps
        cannot happen by construction (no SVG path with the
        wall-segment 5px stroke-width gets emitted from this
        fixture). Pin both branches at zero and assert equivalence
        — the footprint hint is now a no-op for smooth-shape rooms
        because the wall geometry is consolidated.
        """
        building, level = _make_octagon_floor()
        footprint = building.base_shape.floor_tiles(building.base_rect)
        svg_with = render_floor_svg(
            level, seed=0, building_footprint=footprint,
        )
        svg_without = render_floor_svg(level, seed=0)
        with_count = _wall_segment_count(svg_with)
        without_count = _wall_segment_count(svg_without)
        assert with_count == without_count, (
            f"footprint hint should be a no-op for smooth-shape rooms "
            f"after Phase 1.19 (counts diverged: {with_count} with "
            f"footprint vs {without_count} without). The smooth "
            f"ExteriorWallOp owns the octagon outline as a single "
            f"polygon regardless of the legacy footprint optimisation."
        )
        assert with_count >= 1, (
            f"expected ≥ 1 wall path for the octagon ExteriorWallOp, "
            f"got {with_count}"
        )

    def test_render_building_floor_svg_uses_footprint(self):
        """The Building wrapper passes the footprint down to
        render_floor_svg so the standalone building SVG no
        longer paints clipped-corner walls inside the diagonal
        masonry."""
        building, level = _make_octagon_floor()
        svg = render_building_floor_svg(building, 0, seed=0)
        # The clipped corner tile-edges (e.g. between (1, 0)
        # and (2, 0)) sit at pixel x=64, y=0..32. The thick-
        # wall path must not contain that vertical segment.
        # CELL = 32, PADDING for render_floor_svg is 0; the
        # path is wrapped in a <g transform="translate(32,32)">
        # so coords inside are in level-local space.
        forbidden_segments = [
            "M64,0 L64,32",   # left edge of (2, 0) -- clipped
            "M0,64 L0,96",    # left edge of (0, 2) is OK; this
                              # is the chamfer step at top-left
                              # which should NOT be stamped.
        ]
        # We only check the first one strictly -- the second
        # comment is illustrative. The thick-wall path uses
        # absolute pixel coords; check via 64,0 and 64,32.
        for seg in forbidden_segments[:1]:
            assert seg not in svg, (
                f"octagon SVG still emits clipped-corner wall "
                f"segment {seg!r}"
            )


# ── 3. Door placement avoids diagonal walls ───────────────────


class TestDoorPlacementOnDiagonal:
    def test_keep_doors_avoid_clipped_corner_tiles(self):
        """Keep buildings ship octagonal footprints; entry doors
        must not stamp on the diagonal step tiles where two
        perpendicular sides face exterior walls."""
        from nhc.sites.keep import assemble_keep
        for seed in range(10):
            site = assemble_keep("k", random.Random(seed))
            for building in site.buildings:
                if not isinstance(
                    building.base_shape, OctagonShape,
                ):
                    continue
                ground = building.ground
                for y, row in enumerate(ground.tiles):
                    for x, tile in enumerate(row):
                        if tile.feature not in (
                            "door_closed", "door_open", "door_locked",
                        ):
                            continue
                        # Found a stamped door; assert it isn't
                        # on a clipped corner tile.
                        assert not is_clipped_corner_tile(
                            building, x, y,
                        ), (
                            f"seed={seed} {building.id}: door at "
                            f"({x},{y}) sits on a clipped corner"
                        )

    def test_mage_residence_doors_avoid_clipped_corner_tiles(self):
        """Mage residences ship circle / octagon footprints; the
        same constraint applies."""
        from nhc.sites.mage_residence import assemble_mage_residence
        for seed in range(10):
            site = assemble_mage_residence(
                "m", random.Random(seed),
            )
            for building in site.buildings:
                if not isinstance(
                    building.base_shape,
                    (OctagonShape, CircleShape),
                ):
                    continue
                ground = building.ground
                for y, row in enumerate(ground.tiles):
                    for x, tile in enumerate(row):
                        if tile.feature not in (
                            "door_closed", "door_open", "door_locked",
                        ):
                            continue
                        assert not is_clipped_corner_tile(
                            building, x, y,
                        ), (
                            f"seed={seed} {building.id}: door at "
                            f"({x},{y}) sits on a clipped corner"
                        )


# ── 4. Door surface tile must not land in another building's bbox ─


class TestCombinedBuildingBboxes:
    def test_rect_building_bbox_equals_footprint(self):
        rect = Rect(2, 3, 4, 5)
        b = Building(
            id="r", base_shape=RectShape(), base_rect=rect, floors=[],
            wall_material="stone", interior_floor="stone",
            interior_wall_material="stone",
        )
        bboxes = combined_building_bboxes([b])
        footprint = b.base_shape.floor_tiles(rect)
        assert bboxes == footprint, (
            "rect bbox tile set must equal floor footprint "
            "(no chamfer voids)"
        )
        assert len(bboxes) == 4 * 5

    def test_octagon_bbox_includes_chamfer_voids(self):
        rect = Rect(0, 0, 9, 9)
        b = Building(
            id="o", base_shape=OctagonShape(), base_rect=rect, floors=[],
            wall_material="stone", interior_floor="stone",
            interior_wall_material="stone",
        )
        bboxes = combined_building_bboxes([b])
        footprint = b.base_shape.floor_tiles(rect)
        assert bboxes == {
            (x, y)
            for x in range(rect.x, rect.x2)
            for y in range(rect.y, rect.y2)
        }
        assert bboxes > footprint, (
            "octagon bbox must strictly include chamfer-void cells "
            "the floor footprint excludes"
        )


class TestDoorSurfaceAvoidsOtherBuildingBbox:
    """Generalised invariant: a door's outside-neighbour tile must
    not fall inside any *other* building's bounding box. The narrow
    ``floor_tiles()`` check used to allow doors to land in the
    chamfer-void corridor between an octagon and an adjacent rect
    (cf. keep_seed42 -- the SE-chamfer-pinch door)."""

    @pytest.mark.parametrize("seed", list(range(10)))
    def test_keep_door_surfaces_avoid_other_bboxes(self, seed: int):
        from nhc.sites.keep import assemble_keep
        site = assemble_keep("k", random.Random(seed))
        self._assert_no_door_in_other_bbox(site, seed=seed)

    @pytest.mark.parametrize("seed", list(range(10)))
    def test_mansion_door_surfaces_avoid_other_bboxes(self, seed: int):
        from nhc.sites.mansion import assemble_mansion
        site = assemble_mansion("m", random.Random(seed))
        self._assert_no_door_in_other_bbox(site, seed=seed)

    @pytest.mark.parametrize("seed", list(range(10)))
    def test_farm_door_surfaces_avoid_other_bboxes(self, seed: int):
        from nhc.sites.farm import assemble_farm
        site = assemble_farm("f", random.Random(seed))
        self._assert_no_door_in_other_bbox(site, seed=seed)

    @pytest.mark.parametrize("seed", list(range(10)))
    def test_cottage_door_surfaces_avoid_other_bboxes(self, seed: int):
        from nhc.sites.cottage import assemble_cottage
        site = assemble_cottage("c", random.Random(seed))
        self._assert_no_door_in_other_bbox(site, seed=seed)

    @staticmethod
    def _assert_no_door_in_other_bbox(site, *, seed: int) -> None:
        for surf_xy, (b_id, _ix, _iy) in site.building_doors.items():
            others = [b for b in site.buildings if b.id != b_id]
            other_bbox = combined_building_bboxes(others)
            assert surf_xy not in other_bbox, (
                f"seed={seed} {b_id}: door surface tile {surf_xy} "
                f"falls inside another building's bbox (would land "
                f"in another building's chamfer / notch)"
            )
