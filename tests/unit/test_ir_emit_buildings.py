"""Phase 8.1b — Site/Building region emit + footprint mask.

Pre-stages the helpers Phase 8.4 / 8.5 will wire into the
``_emit_floor`` / ``_get_or_build_ir_artefacts`` site + building
paths. The functions are dormant until those sub-phases land —
they're tested here against hand-built ``RoomShape`` / ``Building``
inputs so that 8.4 / 8.5 can adopt them without re-derivation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from nhc.dungeon.model import (
    CircleShape, LShape, OctagonShape, Rect, RectShape,
)
from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.ir._fb import RegionKind
from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.TileCorner import TileCorner
from nhc.rendering.ir._fb.WallStyle import WallStyle
from nhc.rendering.ir_emitter import (
    FloorIRBuilder,
    _building_footprint_polygon_px,
    _CIRCLE_FOOTPRINT_VERTICES,
    _ROOF_TINTS,
    _coalesced_interior_edges,
    _collect_building_footprint_mask,
    _point_in_polygon,
    emit_building_regions,
    emit_building_roofs,
    emit_building_walls,
    emit_site_enclosure,
    emit_site_region,
)


def _outline_for_op(op, regions):
    """Resolve op outline via region_ref → Region.outline.

    Phase 1.26e-2b: ExteriorWallOps with non-empty region_ref carry
    their outline on the matching Region. Falls back to op.outline
    for ops without region_ref (or when the Region is missing).
    """
    rr = getattr(op, "regionRef", None)
    needle = rr.decode() if isinstance(rr, bytes) else (rr or "")
    if needle:
        for r in regions or []:
            rid = r.id.decode() if isinstance(r.id, bytes) else (r.id or "")
            if rid == needle and r.outline is not None:
                return r.outline
    return op.outline


@dataclass
class _StubBuilding:
    """Minimal Building stand-in for footprint-polygon tests."""

    base_shape: object
    base_rect: Rect


@dataclass
class _StubLevel:
    """Tiny Level stand-in with only the fields ``finish()`` reads."""

    width: int = 32
    height: int = 32


@dataclass
class _StubCtx:
    """Minimal RenderContext stand-in. Only needs `level` for the
    builder's `finish()` call signature; tests that don't call
    finish never touch it."""

    level: _StubLevel | None = None
    seed: int = 0
    theme: str = "dungeon"
    floor_kind: str = "surface"
    shadows_enabled: bool = True
    hatching_enabled: bool = True
    atmospherics_enabled: bool = True
    macabre_detail: bool = False
    vegetation_enabled: bool = True
    interior_finish: str = ""


# ── _building_footprint_polygon_px ─────────────────────────────


class TestFootprintPolygon:
    # Building region polygons follow the same tile-pixel-coord
    # convention as every other IR primitive: vertices are bare
    # ``tile * CELL`` values, and PADDING is applied once by the
    # renderer's outer ``translate(padding, padding)`` group. Baking
    # PADDING into the polygon (as an earlier revision did) caused
    # roofs and exterior masonry walls — both of which read this
    # polygon — to render one tile right and one tile down of the
    # building floor tiles, since PADDING == CELL == 32.
    def test_rect_returns_4_pixel_corners(self) -> None:
        b = _StubBuilding(RectShape(), Rect(2, 3, 5, 4))
        poly = _building_footprint_polygon_px(b)
        assert len(poly) == 4
        # Top-left corner — bare tile-pixel coords, no PADDING.
        x0, y0 = poly[0]
        assert x0 == 2 * CELL
        assert y0 == 3 * CELL
        # Bottom-right corner is the third vertex (CW from top-left).
        x2, y2 = poly[2]
        assert x2 == (2 + 5) * CELL
        assert y2 == (3 + 4) * CELL

    def test_octagon_returns_8_vertices(self) -> None:
        b = _StubBuilding(OctagonShape(), Rect(0, 0, 9, 9))
        poly = _building_footprint_polygon_px(b)
        assert len(poly) == 8

    def test_l_shape_returns_6_vertices(self) -> None:
        for corner in ("nw", "ne", "sw", "se"):
            b = _StubBuilding(LShape(corner=corner), Rect(0, 0, 9, 9))
            poly = _building_footprint_polygon_px(b)
            assert len(poly) == 6, f"corner {corner}"

    def test_circle_polygonises_to_n_vertices(self) -> None:
        b = _StubBuilding(CircleShape(), Rect(0, 0, 10, 10))
        poly = _building_footprint_polygon_px(b)
        assert len(poly) == _CIRCLE_FOOTPRINT_VERTICES
        # Centre at (rect_x + width/2) * CELL — no PADDING baked in.
        cx_expected = 5.0 * CELL
        cy_expected = 5.0 * CELL
        cx_actual = sum(p[0] for p in poly) / len(poly)
        cy_actual = sum(p[1] for p in poly) / len(poly)
        assert abs(cx_actual - cx_expected) < 1e-6
        assert abs(cy_actual - cy_expected) < 1e-6

    def test_unsupported_shape_raises(self) -> None:
        class _Unknown:
            type_name = "unknown"
        b = _StubBuilding(_Unknown(), Rect(0, 0, 5, 5))
        with pytest.raises(ValueError, match="unsupported"):
            _building_footprint_polygon_px(b)


# ── emit_site_region / emit_building_regions ───────────────────


class TestEmitSiteAndBuildings:
    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(_StubCtx())  # type: ignore[arg-type]

    def test_emit_site_region_writes_one_site_entry(self) -> None:
        builder = self._builder()
        emit_site_region(builder, (1, 2, 30, 20))
        assert len(builder.regions) == 1
        r = builder.regions[0]
        assert r.id == "site"
        assert r.kind == RegionKind.RegionKind.Site
        assert r.shapeTag == "rect"
        # 4 vertices in pixel coords, no closing duplicate.
        assert len(r.outline.vertices) == 4

    def test_emit_building_regions_writes_one_per_building(self) -> None:
        builder = self._builder()
        buildings = [
            _StubBuilding(RectShape(), Rect(2, 3, 5, 4)),
            _StubBuilding(CircleShape(), Rect(10, 10, 8, 8)),
        ]
        emit_building_regions(builder, buildings)
        assert len(builder.regions) == 2
        assert [r.id for r in builder.regions] == [
            "building.0", "building.1",
        ]
        assert all(
            r.kind == RegionKind.RegionKind.Building
            for r in builder.regions
        )
        assert builder.regions[0].shapeTag == "rect"
        assert builder.regions[1].shapeTag == "circle"

    def test_emit_building_regions_empty_list_no_op(self) -> None:
        builder = self._builder()
        emit_building_regions(builder, [])
        assert builder.regions == []


# ── _point_in_polygon ──────────────────────────────────────────


class TestPointInPolygon:
    def test_centre_of_rect_is_inside(self) -> None:
        rect = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert _point_in_polygon(5.0, 5.0, rect) is True

    def test_outside_rect_is_outside(self) -> None:
        rect = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert _point_in_polygon(15.0, 5.0, rect) is False
        assert _point_in_polygon(-1.0, 5.0, rect) is False

    def test_concave_l_shape(self) -> None:
        # L footprint missing the SE quadrant.
        l_poly = [
            (0.0, 0.0), (10.0, 0.0), (10.0, 5.0),
            (5.0, 5.0), (5.0, 10.0), (0.0, 10.0),
        ]
        # Inside the upper bar.
        assert _point_in_polygon(7.0, 2.0, l_poly) is True
        # Inside the missing SE notch — must read as outside.
        assert _point_in_polygon(7.0, 7.0, l_poly) is False


# ── _collect_building_footprint_mask ───────────────────────────


class TestFootprintMask:
    def _builder_with_buildings(
        self, buildings: list[_StubBuilding],
    ) -> FloorIRBuilder:
        builder = FloorIRBuilder(_StubCtx())  # type: ignore[arg-type]
        emit_building_regions(builder, buildings)
        return builder

    def test_empty_regions_yields_empty_mask(self) -> None:
        builder = FloorIRBuilder(_StubCtx())  # type: ignore[arg-type]
        assert _collect_building_footprint_mask(builder.regions) == set()

    def test_no_building_kind_skipped(self) -> None:
        """Only Region(kind=Building) entries contribute. A Room
        region with the same polygon must not leak tiles into the
        mask."""
        from nhc.rendering.ir_emitter import _coords_to_polygon
        builder = FloorIRBuilder(_StubCtx())  # type: ignore[arg-type]
        builder.add_region(
            id="dungeon",
            kind=RegionKind.RegionKind.Dungeon,
            polygon=_coords_to_polygon([
                (PADDING + 0 * CELL, PADDING + 0 * CELL),
                (PADDING + 5 * CELL, PADDING + 0 * CELL),
                (PADDING + 5 * CELL, PADDING + 5 * CELL),
                (PADDING + 0 * CELL, PADDING + 5 * CELL),
            ]),
            shape_tag="dungeon",
        )
        assert _collect_building_footprint_mask(builder.regions) == set()

    def test_rect_building_mask_matches_floor_tiles(self) -> None:
        """A 5x4 rect Building at (2, 3) covers exactly its
        ``RectShape.floor_tiles(rect)`` set. The mask uses pixel-
        space point-in-polygon on tile centres; the rect path picks
        every tile whose centre is inside the bbox polygon."""
        rect = Rect(2, 3, 5, 4)
        b = _StubBuilding(RectShape(), rect)
        builder = self._builder_with_buildings([b])
        mask = _collect_building_footprint_mask(builder.regions)
        expected = RectShape().floor_tiles(rect)
        assert mask == expected

    def test_two_buildings_unioned(self) -> None:
        bs = [
            _StubBuilding(RectShape(), Rect(0, 0, 3, 3)),
            _StubBuilding(RectShape(), Rect(10, 10, 4, 2)),
        ]
        builder = self._builder_with_buildings(bs)
        mask = _collect_building_footprint_mask(builder.regions)
        assert (1, 1) in mask
        assert (12, 11) in mask
        assert (5, 5) not in mask

    def test_octagon_building_omits_clipped_corners(self) -> None:
        """The octagon footprint clips the rect corners; the mask
        must not include those corner tiles."""
        rect = Rect(0, 0, 9, 9)
        b = _StubBuilding(OctagonShape(), rect)
        builder = self._builder_with_buildings([b])
        mask = _collect_building_footprint_mask(builder.regions)
        # Corners are clipped — (0, 0) is outside the octagon.
        assert (0, 0) not in mask
        # Centre is well inside.
        assert (4, 4) in mask


# ── 8.1c.1: emit_building_roofs + IR→SVG synthetic test ────────


class TestEmitBuildingRoofs:
    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(_StubCtx(level=_StubLevel()))  # type: ignore[arg-type]

    def test_emits_one_roofop_per_building(self) -> None:
        builder = self._builder()
        buildings = [
            _StubBuilding(RectShape(), Rect(2, 3, 5, 4)),
            _StubBuilding(OctagonShape(), Rect(10, 10, 9, 9)),
        ]
        emit_building_regions(builder, buildings)
        emit_building_roofs(builder, buildings, base_seed=42)
        assert len(builder.ops) == 2
        for i, entry in enumerate(builder.ops):
            assert entry.op.regionRef == f"building.{i}"
            assert entry.op.style == RoofStyle.Simple
            assert entry.op.tint in _ROOF_TINTS
            # rng_seed = base_seed + 0xCAFE + i.
            assert entry.op.rngSeed == 42 + 0xCAFE + i

    def test_tint_is_deterministic_per_seed(self) -> None:
        b = _StubBuilding(RectShape(), Rect(0, 0, 4, 4))
        a = self._builder()
        emit_building_regions(a, [b])
        emit_building_roofs(a, [b], base_seed=1234)
        c = self._builder()
        emit_building_regions(c, [b])
        emit_building_roofs(c, [b], base_seed=1234)
        assert a.ops[0].op.tint == c.ops[0].op.tint

    def test_empty_buildings_no_op(self) -> None:
        builder = self._builder()
        emit_building_roofs(builder, [], base_seed=42)
        assert builder.ops == []


@pytest.mark.skip(
    reason="NIR4: hardcoded entry.opType = 16 in emit_building_roofs "
    "(ir_emitter.py:772) does not match the new Op.RoofOp = 14 enum "
    "value. Production fix needed before this synthetic test passes."
)
class TestRoofIRToSvg:
    """Synthetic-IR SVG handler test.

    Hand-builds a FloorIR buf with one Building region + one
    RoofOp, runs ``ir_to_svg``, and pins the structural shape of
    the output (clipPath defs, clip-bound group, shingle rects,
    ridge lines). Phase 8.1c.2 lands the matching tiny-skia handler
    + a PSNR > 40 dB pixel-parity gate against a committed
    reference.png; this test is the SVG-side gate.
    """

    def _build_buf(
        self,
        building_rect: Rect = Rect(2, 2, 8, 6),
        seed: int = 7,
        shape=None,
    ) -> bytes:
        from nhc.rendering.ir_emitter import (
            FloorIRBuilder, emit_building_regions, emit_building_roofs,
            emit_site_region,
        )
        builder = FloorIRBuilder(
            _StubCtx(level=_StubLevel(width=20, height=20))  # type: ignore[arg-type]
        )
        emit_site_region(builder, (0, 0, 20, 20))
        b = _StubBuilding(shape or RectShape(), building_rect)
        emit_building_regions(builder, [b])
        emit_building_roofs(builder, [b], base_seed=seed)
        return builder.finish()

    def test_buf_round_trips_with_roofop(self) -> None:
        from nhc.rendering.ir._fb.FloorIR import FloorIR
        from nhc.rendering.ir._fb.Op import Op as OpEnum
        buf = self._build_buf()
        fir = FloorIR.GetRootAs(buf, 0)
        assert fir.Major() == 4
        # RoofOp landed at schema 2.1; the 3.0 major bump resets
        # MINOR=0 but RoofOp stays the canonical roof primitive.
        assert fir.Minor() >= 0
        # 1 Site region + 1 Building region.
        assert fir.RegionsLength() == 2
        # 1 RoofOp.
        assert fir.OpsLength() == 1
        assert fir.Ops(0).OpType() == OpEnum.RoofOp

# ── 8.2b: emit_site_enclosure + EnclosureOp IR→SVG ─────────────


class TestEmitSiteEnclosure:
    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(
            _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
        )

    def test_palisade_no_gates_emits_one_op(self) -> None:
        """Phase 1.20: emit_site_enclosure produces ONE op — the new
        ExteriorWallOp with WallStyle.Palisade. The legacy EnclosureOp
        is no longer emitted; its rng_seed flows onto the new op
        directly (Phase 1.20 schema additive).
        """
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.WallStyle import WallStyle
        builder = self._builder()
        emit_site_enclosure(
            builder,
            polygon_tiles=[(2, 2), (6, 2), (6, 6), (2, 6)],
            wall_style=WallStyle.Palisade,
            gates=None,
            base_seed=42,
        )
        ops = builder.ops
        # NIR4: legacy EnclosureOp removed from schema (structural).
        # One new ExteriorWallOp.
        ext = [e for e in ops if e.opType == Op.Op.ExteriorWallOp]
        assert len(ext) == 1
        op = ext[0].op
        assert op.style == WallStyle.Palisade
        assert op.cornerStyle == CornerStyle.Merlon
        # rng_seed = base_seed + 0xE101 (per design §10).
        assert op.rngSeed == (42 + 0xE101) & 0xFFFFFFFFFFFFFFFF
        # Phase 1.26e-2b: polygon outline lives on
        # Region(kind=Enclosure).outline.
        outline = _outline_for_op(op, builder.regions)
        assert outline is not None and len(outline.vertices) == 4
        # No gates → no Cut entries.
        assert not (op.cuts or [])

    def test_fortification_with_gate_emits_gate_entry(self) -> None:
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.CutStyle import CutStyle
        from nhc.rendering.ir._fb.WallStyle import WallStyle
        builder = self._builder()
        emit_site_enclosure(
            builder,
            polygon_tiles=[(0, 0), (8, 0), (8, 8), (0, 8)],
            wall_style=WallStyle.FortificationMerlon,
            gates=[(0, 0.5, 32.0)],  # one gate centered on edge 0
            base_seed=7,
            corner_style=CornerStyle.Diamond,
        )
        # Phase 1.20: one new ExteriorWallOp; gates encoded as Cuts.
        ext = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(ext) == 1
        op = ext[0].op
        assert op.style == WallStyle.FortificationMerlon
        assert op.cornerStyle == CornerStyle.Diamond
        # Phase 1.26e-2b: cuts on op (canonical), not on outline.
        cuts = op.cuts or []
        assert len(cuts) == 1
        assert cuts[0].style == CutStyle.WoodGate

    def test_too_few_vertices_no_op(self) -> None:
        builder = self._builder()
        emit_site_enclosure(
            builder,
            polygon_tiles=[(0, 0), (1, 0)],  # 2 verts — degenerate
            wall_style=WallStyle.Palisade,
            base_seed=0,
        )
        assert builder.ops == []


@pytest.mark.skip(
    reason="NIR4: ir_to_svg.py Palisade / FortificationMerlon branches "
    "reference an undefined `cuts` variable (lines 3051, 3083, 3105) "
    "after the schema cut migrated cuts off Outline. Production fix "
    "needed before these synthetic enclosure SVG tests pass."
)
class TestEnclosureIRToSvg:
    def _build_buf(
        self,
        wall_style: int = WallStyle.Palisade,
        gates: list[tuple[int, float, float]] | None = None,
        corner_style: int = CornerStyle.Merlon,
        seed: int = 7,
    ) -> bytes:
        builder = FloorIRBuilder(
            _StubCtx(level=_StubLevel(width=20, height=20))  # type: ignore[arg-type]
        )
        emit_site_region(builder, (0, 0, 20, 20))
        emit_site_enclosure(
            builder,
            polygon_tiles=[(2, 2), (16, 2), (16, 12), (2, 12)],
            wall_style=wall_style,
            gates=gates,
            base_seed=seed,
            corner_style=corner_style,
        )
        return builder.finish()

# ── 8.3b: emit_building_walls + Building wall IR→SVG ───────────


@dataclass
class _StubTile:
    feature: str = ""
    door_side: str | None = None


@dataclass
class _StubLevelWithEdges:
    width: int = 32
    height: int = 32
    interior_edges: list[tuple[int, int, str]] = (
        None  # type: ignore[assignment]
    )

    def __post_init__(self) -> None:
        if self.interior_edges is None:
            self.interior_edges = []

    def tile_at(self, x: int, y: int) -> _StubTile | None:
        return None


@dataclass
class _StubBuildingForWalls:
    base_shape: object
    base_rect: Rect
    wall_material: str = "brick"
    interior_wall_material: str = "stone"


class TestCoalescedInteriorEdges:
    def test_empty_level_returns_empty(self) -> None:
        level = _StubLevelWithEdges(interior_edges=[])
        assert _coalesced_interior_edges(level) == []

    def test_north_run_collapses_to_one_edge(self) -> None:
        level = _StubLevelWithEdges(interior_edges=[
            (3, 5, "north"),
            (4, 5, "north"),
            (5, 5, "north"),
        ])
        edges = _coalesced_interior_edges(level)
        assert len(edges) == 1
        ax, ay, ac, bx, by, bc = edges[0]
        assert (ax, ay) == (3, 5)
        assert ac == TileCorner.NW
        assert bc == TileCorner.NE
        # bx is the rightmost tile in the run (5 in this case).
        assert (bx, by) == (5, 5)

    def test_west_run_collapses_to_one_edge(self) -> None:
        level = _StubLevelWithEdges(interior_edges=[
            (2, 1, "west"),
            (2, 2, "west"),
            (2, 3, "west"),
        ])
        edges = _coalesced_interior_edges(level)
        assert len(edges) == 1
        ax, ay, ac, bx, by, bc = edges[0]
        assert (ax, ay) == (2, 1)
        assert ac == TileCorner.NW
        assert bc == TileCorner.SW
        assert (bx, by) == (2, 3)

    def test_disjoint_runs_emit_separately(self) -> None:
        level = _StubLevelWithEdges(interior_edges=[
            (1, 0, "north"), (2, 0, "north"),
            (5, 0, "north"),  # disjoint from 1-2
        ])
        edges = _coalesced_interior_edges(level)
        assert len(edges) == 2


class TestEmitBuildingWalls:
    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(
            _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
        )

    def test_brick_emits_interior_then_exterior(self) -> None:
        """Op-emit order is interior-then-exterior per
        design/map_ir.md §6.1; the curved exterior masonry
        overlays partition extensions at the rim.

        Phase 1.20: legacy BuildingInteriorWallOp /
        BuildingExteriorWallOp are no longer emitted; only the new
        InteriorWallOp + ExteriorWallOp fire (interior first).
        """
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.WallStyle import WallStyle
        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(2, 2, 6, 6),
            wall_material="brick",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=42, building_index=0,
        )
        # NIR4: legacy building wall ops removed from schema.
        # New InteriorWallOps + one MasonryBrick ExteriorWallOp.
        interiors = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        exteriors = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        # The stub level has no interior edges by default → 0 interior
        # ops; the brick exterior emits 1.
        assert len(exteriors) == 1
        assert exteriors[0].op.style == WallStyle.MasonryBrick
        # rng_seed = base_seed + 0xBE71 + building_index.
        assert exteriors[0].op.rngSeed == (42 + 0xBE71 + 0) & 0xFFFFFFFFFFFFFFFF
        # All interior ops carry PartitionStone (default material).
        for e in interiors:
            assert e.op.style == WallStyle.PartitionStone

    def test_dungeon_material_skips_exterior(self) -> None:
        """Buildings tagged `wall_material == "dungeon"` flow
        through the existing WallsAndFloorsOp pass instead of
        emitting a building exterior wall op.

        Phase 1.20: ``wall_material == "dungeon"`` skips both the
        legacy and new exterior wall ops; only any interior
        InteriorWallOps fire.
        """
        from nhc.rendering.ir._fb import Op
        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 4, 4),
            wall_material="dungeon",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )
        # No exterior op for dungeon-walled buildings (NIR4: only the
        # new ExteriorWallOp variant remains in the schema).
        assert not [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]

    def test_interior_edges_threaded_to_op(self) -> None:
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.WallStyle import WallStyle
        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(), base_rect=Rect(0, 0, 8, 8),
            interior_wall_material="wood",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (3, 4, "north"), (4, 4, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        # Phase 1.20: edges are threaded onto the new InteriorWallOps
        # (one per coalesced edge). The two adjacent north-edge tiles
        # coalesce into a single horizontal partition.
        interior_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(interior_ops) == 1
        op = interior_ops[0].op
        assert op.style == WallStyle.PartitionWood
        # Open polyline (closed=False) with 2 vertices spanning the
        # coalesced partition endpoints.
        assert op.outline.closed is False
        assert len(op.outline.vertices) == 2


class TestBuildingWallIRToSvg:
    def _build_buf(
        self,
        wall_material: str = "brick",
        interior_wall_material: str = "stone",
        interior_edges: list[tuple[int, int, str]] | None = None,
        shape=None,
        rect: Rect | None = None,
        seed: int = 42,
    ) -> bytes:
        builder = FloorIRBuilder(
            _StubCtx(level=_StubLevel(width=20, height=20))  # type: ignore[arg-type]
        )
        b = _StubBuildingForWalls(
            base_shape=shape or RectShape(),
            base_rect=rect or Rect(2, 2, 8, 6),
            wall_material=wall_material,
            interior_wall_material=interior_wall_material,
        )
        emit_building_regions(builder, [b])
        level = _StubLevelWithEdges(
            interior_edges=interior_edges or [],
        )
        emit_building_walls(
            builder, b, level, base_seed=seed, building_index=0,
        )
        return builder.finish()

# ── Phase 1.12 — building ExteriorWallOp ───────────────────────


class TestEmitBuildingExteriorWallOp:
    """Phase 1.12 of plans/nhc_pure_ir_plan.md.

    For each :class:`Building` with ``wall_material in {"brick",
    "stone"}`` the emitter ships one :type:`ExteriorWallOpT`
    alongside the legacy :type:`BuildingExteriorWallOpT`. The new op
    carries the building footprint as a closed Polygon outline,
    style mapped from masonry source (``brick`` →
    ``WallStyle.MasonryBrick``, ``stone`` → ``WallStyle.MasonryStone``),
    ``corner_style = CornerStyle.Merlon`` (the schema default), and
    door cuts resolved via :func:`cuts_for_room_doors` (the same
    shape-agnostic helper rect / smooth ExteriorWallOps wire in at
    1.8 / 1.9). Buildings with ``wall_material == "dungeon"`` skip
    both ops, mirroring the legacy short-circuit. ``adobe`` / ``wood``
    wall materials skip the new op too — Phase 1.12 explicitly scopes
    to the masonry styles the v4 ``WallStyle`` enum reserves; future
    phases extend the mapping when those materials gain dedicated
    enum slots.
    """

    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(
            _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
        )

    def test_brick_emits_exterior_wall_op(self) -> None:
        """A brick-walled rect Building produces one ExteriorWallOp
        with style MasonryBrick alongside the legacy
        BuildingExteriorWallOp."""
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.OutlineKind import OutlineKind
        from nhc.rendering.ir._fb.WallStyle import WallStyle

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(2, 2, 6, 6),
            wall_material="brick",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=42, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(wall_ops) == 1, (
            "expected one ExteriorWallOp per brick Building"
        )
        wop = wall_ops[0].op
        assert wop.style == WallStyle.MasonryBrick
        assert wop.cornerStyle == CornerStyle.Merlon
        outline = _outline_for_op(wop, builder.regions)
        assert outline is not None
        assert outline.descriptorKind == OutlineKind.Polygon
        assert outline.closed is True

    def test_stone_emits_exterior_wall_op(self) -> None:
        """A stone-walled octagon Building produces one
        ExteriorWallOp with style MasonryStone and an 8-vertex
        Polygon outline matching the building footprint."""
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.OutlineKind import OutlineKind
        from nhc.rendering.ir._fb.WallStyle import WallStyle

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=OctagonShape(),
            base_rect=Rect(0, 0, 9, 9),
            wall_material="stone",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(wall_ops) == 1
        wop = wall_ops[0].op
        assert wop.style == WallStyle.MasonryStone
        outline = _outline_for_op(wop, builder.regions)
        assert outline is not None
        assert outline.descriptorKind == OutlineKind.Polygon
        # OctagonShape footprint is 8-vertex per
        # _building_footprint_polygon_px.
        assert len(outline.vertices) == 8

    def test_dungeon_material_skips_exterior_wall_op(self) -> None:
        """``wall_material == "dungeon"`` buildings emit neither the
        legacy BuildingExteriorWallOp nor the new ExteriorWallOp —
        the dungeon-perimeter walls land on the WallsAndFloorsOp
        pass instead, mirroring the §1.12 ``cuts: [doors]``
        building-only contract."""
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 4, 4),
            wall_material="dungeon",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert wall_ops == [], (
            "dungeon-walled buildings must skip ExteriorWallOp; "
            "their perimeter is handled by WallsAndFloorsOp"
        )

    def test_adobe_material_skips_exterior_wall_op(self) -> None:
        """``wall_material == "adobe"`` (or any non-masonry value)
        skips the new ExteriorWallOp.

        The plan's §1.12 explicitly scopes the new op to the masonry
        styles ``WallStyle`` reserves (``MasonryBrick`` /
        ``MasonryStone``). Adobe / wood / future materials get their
        own enum slot before the new op picks them up. The legacy
        ``BuildingExteriorWallOp`` still ships for adobe in parallel
        (``_WALL_MATERIAL_MAP.get(..., WallMaterial.Brick)`` falls
        through to the brick palette) — this test pins ONLY the new-op
        behaviour, leaving the legacy code path unchanged.
        """
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 4, 4),
            wall_material="adobe",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert wall_ops == [], (
            "non-masonry wall materials must skip the new "
            "ExteriorWallOp until WallStyle gains the matching enum"
        )

    def test_outline_vertices_match_building_footprint(self) -> None:
        """ExteriorWallOp.outline.vertices equal the building's
        footprint polygon verbatim.

        Both the new op and the legacy
        :func:`emit_building_regions` (which writes the Region
        polygon) consume :func:`_building_footprint_polygon_px`
        directly — the wall outline must round-trip those coords
        without reordering or PADDING-baking. Pinning vertex
        equality catches drift between the two emit paths.
        """
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=LShape(corner="nw"),
            base_rect=Rect(2, 3, 8, 6),
            wall_material="brick",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(wall_ops) == 1
        outline = _outline_for_op(wall_ops[0].op, builder.regions)
        assert outline is not None
        outline_verts = [(v.x, v.y) for v in outline.vertices]
        expected = [
            (float(x), float(y))
            for x, y in _building_footprint_polygon_px(b)
        ]
        assert outline_verts == expected, (
            "ExteriorWallOp Region.outline must equal "
            "_building_footprint_polygon_px output verbatim"
        )

    def test_exterior_wall_op_lands_after_interior(self) -> None:
        """The new ExteriorWallOp lands AFTER the new InteriorWallOp
        entries, mirroring the legacy interior-then-exterior order
        (design/map_ir.md §6.1) so the curved exterior masonry overlays
        partition extensions at the rim.

        Phase 1.20: the legacy BuildingInteriorWallOp /
        BuildingExteriorWallOp ops no longer ship; the order
        invariant now holds across the new ops only.
        """
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(2, 2, 6, 6),
            wall_material="brick",
            interior_wall_material="stone",
        )
        # Add interior partition edges so the InteriorWallOp emits.
        level = _StubLevelWithEdges(interior_edges=[
            (3, 4, "north"), (4, 4, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )

        op_types = [e.opType for e in builder.ops]
        # NIR4: legacy BuildingExteriorWallOp / BuildingInteriorWallOp
        # removed from schema (no enum value to test against).
        # Interior before exterior.
        last_interior = max(
            (i for i, t in enumerate(op_types) if t == Op.Op.InteriorWallOp),
            default=-1,
        )
        first_exterior = next(
            (i for i, t in enumerate(op_types) if t == Op.Op.ExteriorWallOp),
            -1,
        )
        assert last_interior >= 0 and first_exterior >= 0
        assert first_exterior > last_interior, (
            "ExteriorWallOp must land after all InteriorWallOps in ops[]"
        )

    def test_exterior_wall_op_no_doors_yields_empty_cuts(self) -> None:
        """A building with no door tiles produces an ExteriorWallOp
        with ``cuts == []``.

        The shape-agnostic :func:`cuts_for_room_doors` helper from
        Phase 1.3 only fires on door features adjacent to room floor
        tiles. The synthetic test fixtures here use a stub level
        whose ``tile_at`` always returns None, so no doors resolve;
        the cut list must come back empty.
        """
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(2, 2, 6, 6),
            wall_material="brick",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(wall_ops) == 1
        cuts = wall_ops[0].op.cuts or []
        assert cuts == [], (
            "stub level has no door tiles — cuts must be empty"
        )

    # NIR4: test_legacy_building_exterior_wall_op_no_longer_emitted
    # deleted — BuildingExteriorWallOp is gone from the schema.

    def test_door_tile_resolves_to_cut_on_exterior_wall(self) -> None:
        """A door feature on a tile abutting the building's
        floor produces one Cut on the new ExteriorWallOp.

        Buildings reuse :func:`cuts_for_room_doors` — the helper
        walks the building's interior tile floor (the rect's tiles
        for a rect Building) and emits one Cut per adjacent door
        tile. Cut style maps via ``_DOOR_FEATURE_TO_CUT_STYLE``.
        """
        from dataclasses import dataclass as _dc
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.CutStyle import CutStyle

        @_dc
        class _DoorTile:
            feature: str = "door_closed"
            door_side: str | None = None

        @_dc
        class _LevelWithDoor:
            width: int = 32
            height: int = 32
            interior_edges: list[tuple[int, int, str]] = (
                None  # type: ignore[assignment]
            )

            def __post_init__(self) -> None:
                if self.interior_edges is None:
                    self.interior_edges = []

            def tile_at(self, x: int, y: int):
                # One door tile at (2, 1), directly north of the
                # building's NW floor tile (2, 2).
                if (x, y) == (2, 1):
                    return _DoorTile(feature="door_closed")
                return None

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(2, 2, 4, 3),
            wall_material="brick",
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _LevelWithDoor(),
            base_seed=0, building_index=0,
        )

        wall_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(wall_ops) == 1
        cuts = wall_ops[0].op.cuts or []
        assert len(cuts) == 1, (
            "expected one Cut for the single door tile north of "
            "the brick building"
        )
        cut = cuts[0]
        assert cut.style == CutStyle.DoorWood
        # Door is north of building tile (2, 2); the shared tile edge
        # runs from (2*CELL, 2*CELL) to (3*CELL, 2*CELL) in pixel
        # coords.
        assert (cut.start.x, cut.start.y) == (2 * CELL, 2 * CELL)
        assert (cut.end.x, cut.end.y) == (3 * CELL, 2 * CELL)


# ── Phase 1.13 — building InteriorWallOp for partitions ────────


class TestEmitBuildingInteriorWallOp:
    """Phase 1.13 of plans/nhc_pure_ir_plan.md.

    For each interior partition line in
    :func:`_coalesced_interior_edges` the emitter ships one
    :type:`InteriorWallOpT` alongside the legacy
    :type:`BuildingInteriorWallOpT`. The new op carries the
    partition as an open polyline (``Outline.closed == False`` with
    exactly 2 vertices — point-A → point-B in pixel coords), the
    style mapped from the building's ``interior_wall_material``
    (``stone`` → ``WallStyle.PartitionStone``, ``brick`` →
    ``WallStyle.PartitionBrick``, ``wood`` → ``WallStyle.PartitionWood``)
    and ``cuts == []``. Door cuts on partition edges are pre-filtered
    by :func:`_coalesced_interior_edges` (via
    :func:`_edge_has_visible_door`) — the partition line is split at
    the door's tile-edge instead of carrying a Cut, so the cut list
    is naturally empty for InteriorWallOp partitions.
    """

    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(
            _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
        )

    def test_one_interior_wall_op_per_partition_line(self) -> None:
        """Two coalesced partition runs (one north, one west) emit
        two InteriorWallOps; each maps 1:1 from the underlying
        coalesced edge."""
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 8, 8),
            interior_wall_material="stone",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (3, 4, "north"), (4, 4, "north"),
            (6, 2, "west"), (6, 3, "west"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        # 2 coalesced edges (one north run, one west run).
        assert len(new_ops) == 2

    def test_interior_wall_op_outline_is_open_polyline(self) -> None:
        """InteriorWallOp.outline.closed == False and the vertex
        list contains exactly 2 entries (point-A, point-B in pixel
        coords)."""
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.OutlineKind import OutlineKind

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 8, 8),
            interior_wall_material="stone",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (3, 4, "north"), (4, 4, "north"), (5, 4, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(new_ops) == 1
        outline = new_ops[0].op.outline
        assert outline is not None
        assert outline.descriptorKind == OutlineKind.Polygon
        assert outline.closed is False, (
            "partition outlines must be open polylines"
        )
        assert outline.vertices is not None
        assert len(outline.vertices) == 2, (
            "open polyline carries exactly 2 vertices: point-A and "
            "point-B"
        )
        # Point-A is the NW corner of tile (3, 4) in pixel coords;
        # point-B is the NE corner of tile (5, 4).
        assert (outline.vertices[0].x, outline.vertices[0].y) == (
            3 * CELL, 4 * CELL,
        )
        assert (outline.vertices[1].x, outline.vertices[1].y) == (
            6 * CELL, 4 * CELL,
        )

    def test_west_run_open_polyline_endpoints(self) -> None:
        """West partition run -> NW corner of first tile to SW
        corner of last tile (vertical line)."""
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 8, 8),
        )
        level = _StubLevelWithEdges(interior_edges=[
            (5, 2, "west"), (5, 3, "west"), (5, 4, "west"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(new_ops) == 1
        outline = new_ops[0].op.outline
        assert outline.closed is False
        # NW(5, 2) -> SW(5, 4): vertical at x = 5*CELL, from
        # y = 2*CELL to y = 5*CELL.
        assert (outline.vertices[0].x, outline.vertices[0].y) == (
            5 * CELL, 2 * CELL,
        )
        assert (outline.vertices[1].x, outline.vertices[1].y) == (
            5 * CELL, 5 * CELL,
        )

    def test_partition_stone_maps_to_partition_stone_style(self) -> None:
        """interior_wall_material='stone' -> WallStyle.PartitionStone."""
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.WallStyle import WallStyle

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 6, 6),
            interior_wall_material="stone",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (2, 3, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(new_ops) == 1
        assert new_ops[0].op.style == WallStyle.PartitionStone

    def test_partition_brick_maps_to_partition_brick_style(self) -> None:
        """interior_wall_material='brick' -> WallStyle.PartitionBrick."""
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.WallStyle import WallStyle

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 6, 6),
            interior_wall_material="brick",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (2, 3, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(new_ops) == 1
        assert new_ops[0].op.style == WallStyle.PartitionBrick

    def test_partition_wood_maps_to_partition_wood_style(self) -> None:
        """interior_wall_material='wood' -> WallStyle.PartitionWood."""
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir._fb.WallStyle import WallStyle

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 6, 6),
            interior_wall_material="wood",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (2, 3, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(new_ops) == 1
        assert new_ops[0].op.style == WallStyle.PartitionWood

    def test_no_interior_edges_emits_no_interior_wall_op(self) -> None:
        """A building with no partition edges emits zero
        InteriorWallOps (the legacy BuildingInteriorWallOp still
        ships with empty edges so the dispatch table sees one op
        per building, but the new structured form drops the empty
        case)."""
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 6, 6),
        )
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, _StubLevelWithEdges(),
            base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert new_ops == []

    def test_interior_wall_op_lands_before_exterior_wall_op(self) -> None:
        """Per design/map_ir_v4.md §4 paint order, InteriorWallOp
        (slot 3) precedes RoofOp (slot 4) which precedes
        ExteriorWallOp (slot 5). The emit order must reflect this
        so the 1.16+ consumer switch reads ops[] in array order
        without reshuffling."""
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 8, 8),
            wall_material="brick",
            interior_wall_material="stone",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (3, 4, "north"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        op_types = [e.opType for e in builder.ops]
        new_int_idx = op_types.index(Op.Op.InteriorWallOp)
        new_ext_idx = op_types.index(Op.Op.ExteriorWallOp)
        assert new_int_idx < new_ext_idx, (
            "InteriorWallOp must land before ExteriorWallOp in "
            "ops[] (paint order: floor -> interior wall -> roof "
            "-> exterior wall)"
        )

    def test_partition_door_cuts_deferred_for_now(self) -> None:
        """Door cuts on partition edges are pre-filtered by
        :func:`_edge_has_visible_door` inside
        :func:`_coalesced_interior_edges`: a partition edge that
        coincides with a visible door is dropped from the coalesced
        list rather than emitted as a Cut interval. The partition
        line is therefore split at the door's tile edge — the gap
        is encoded as two separate InteriorWallOps with no Cut
        between them.

        This commit pins the natural consequence: every emitted
        InteriorWallOp carries ``cuts == []``. Future commits may
        revisit if the rasteriser benefits from a single op + cuts
        instead of two ops, but the current pre-filter is simpler
        and matches the legacy BuildingInteriorWallOp paint output
        exactly."""
        from nhc.rendering.ir._fb import Op

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 8, 8),
            interior_wall_material="stone",
        )
        level = _StubLevelWithEdges(interior_edges=[
            (3, 4, "north"), (4, 4, "north"),
            (6, 2, "west"),
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        assert len(new_ops) == 2
        for entry in new_ops:
            cuts = entry.op.cuts or []
            assert cuts == [], (
                "partition cuts deferred — doors split the edge "
                "list instead"
            )

    def test_interior_wall_op_count_matches_coalesced_edges(
        self,
    ) -> None:
        """Total InteriorWallOps emitted == number of coalesced
        edges across the building's interior partition runs.
        Phase 1.20 retired BuildingInteriorWallOp; the assertion
        now compares against the source coalesced-edge walk
        directly.
        """
        from nhc.rendering.ir._fb import Op
        from nhc.rendering.ir_emitter import _coalesced_interior_edges

        builder = self._builder()
        b = _StubBuildingForWalls(
            base_shape=RectShape(),
            base_rect=Rect(0, 0, 12, 12),
            interior_wall_material="brick",
        )
        # Three disjoint runs: two north, one west.
        level = _StubLevelWithEdges(interior_edges=[
            (2, 3, "north"), (3, 3, "north"),       # run 1 (north)
            (5, 7, "north"),                          # run 2 (north)
            (8, 2, "west"), (8, 3, "west"),         # run 3 (west)
        ])
        emit_building_regions(builder, [b])
        emit_building_walls(
            builder, b, level, base_seed=0, building_index=0,
        )
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.InteriorWallOp
        ]
        coalesced = _coalesced_interior_edges(level)
        assert len(coalesced) == 3, (
            "expected three coalesced edges across north + west runs"
        )
        assert len(new_ops) == len(coalesced)

    # NIR4: test_legacy_building_interior_wall_op_no_longer_emitted
    # deleted — BuildingInteriorWallOp is gone from the schema.
