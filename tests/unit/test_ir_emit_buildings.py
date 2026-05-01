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
from nhc.rendering.ir._fb.EnclosureStyle import EnclosureStyle
from nhc.rendering.ir._fb.GateStyle import GateStyle
from nhc.rendering.ir._fb.InteriorWallMaterial import InteriorWallMaterial
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.TileCorner import TileCorner
from nhc.rendering.ir._fb.WallMaterial import WallMaterial
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
        assert len(r.polygon.paths) == 4

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
        assert fir.Major() == 3
        # RoofOp landed at schema 2.1; the 3.0 major bump resets
        # MINOR=0 but RoofOp stays the canonical roof primitive.
        assert fir.Minor() >= 0
        # 1 Site region + 1 Building region.
        assert fir.RegionsLength() == 2
        # 1 RoofOp.
        assert fir.OpsLength() == 1
        assert fir.Ops(0).OpType() == OpEnum.RoofOp

    def test_svg_contains_clip_path_defs_and_group(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf()
        svg = ir_to_svg(buf)
        # Layer comment for the structural layer.
        assert "<!-- layer.structural:" in svg
        # ClipPath defs anchored on the building's region_ref.
        assert '<clipPath id="roof_building_0">' in svg
        # Group references the same clipPath id.
        assert 'clip-path="url(#roof_building_0)"' in svg

    def test_rect_non_square_emits_gable(self) -> None:
        """Wide rect → gable: 2 shingle halves + 1 ridge line."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(building_rect=Rect(0, 0, 10, 4))
        svg = ir_to_svg(buf)
        # Gable emits exactly one ridge <line>; pyramid emits N
        # ridge spokes (N == polygon vertex count).
        assert svg.count(f'stroke-width="1.5"/>') == 1

    def test_rect_square_emits_pyramid(self) -> None:
        """Square rect → pyramid: 4 triangles + 4 ridge spokes."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(building_rect=Rect(0, 0, 6, 6))
        svg = ir_to_svg(buf)
        # 4 polygon spokes from centre.
        assert svg.count(f'stroke-width="1.5"/>') == 4

    def test_octagon_emits_pyramid(self) -> None:
        """Octagon footprint → pyramid: 8 triangles + 8 spokes."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(
            building_rect=Rect(0, 0, 9, 9), shape=OctagonShape(),
        )
        svg = ir_to_svg(buf)
        assert svg.count(f'stroke-width="1.5"/>') == 8

    def test_circle_emits_pyramid(self) -> None:
        """Circle footprint → pyramid on the polygonised N-gon —
        Phase 8.1 drops the legacy Circle-skip branch per
        design/map_ir.md §7.14."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(
            building_rect=Rect(0, 0, 8, 8), shape=CircleShape(),
        )
        svg = ir_to_svg(buf)
        # N spokes == _CIRCLE_FOOTPRINT_VERTICES.
        assert svg.count(f'stroke-width="1.5"/>') == _CIRCLE_FOOTPRINT_VERTICES

    def test_svg_is_deterministic_per_seed(self) -> None:
        """Same seed -> identical SVG. Both builds run through the
        full splitmix64 stream; any drift in the RNG, palette, or
        layout would surface here."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        a = ir_to_svg(self._build_buf(seed=99))
        b = ir_to_svg(self._build_buf(seed=99))
        assert a == b

    def test_unknown_region_raises(self) -> None:
        """A RoofOp pointing at a missing region is an emit-side
        contract violation — the handler must error, not paint
        nothing silently."""
        from nhc.rendering.ir._fb.OpEntry import OpEntryT
        from nhc.rendering.ir._fb.RoofOp import RoofOpT  # noqa: F401
        from nhc.rendering.ir._fb.RoofStyle import RoofStyle  # noqa: F401
        from nhc.rendering.ir_to_svg import ir_to_svg
        builder = FloorIRBuilder(
            _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
        )
        # No regions added; RoofOp references a non-existent id.
        bad = RoofOpT(
            regionRef="building.0",
            style=RoofStyle.Simple,
            tint="#8A8A8A",
            rngSeed=1,
        )
        entry = OpEntryT()
        entry.opType = 16
        entry.op = bad
        builder.add_op(entry)
        buf = builder.finish()
        with pytest.raises(ValueError, match="unknown region"):
            ir_to_svg(buf)


# ── 8.2b: emit_site_enclosure + EnclosureOp IR→SVG ─────────────


class TestEmitSiteEnclosure:
    def _builder(self) -> FloorIRBuilder:
        return FloorIRBuilder(
            _StubCtx(level=_StubLevel())  # type: ignore[arg-type]
        )

    def test_palisade_no_gates_emits_one_op(self) -> None:
        builder = self._builder()
        # 4×4 tile rect at (2, 2).
        emit_site_enclosure(
            builder,
            polygon_tiles=[(2, 2), (6, 2), (6, 6), (2, 6)],
            style=EnclosureStyle.Palisade,
            gates=None,
            base_seed=42,
        )
        assert len(builder.ops) == 1
        op = builder.ops[0].op
        assert op.style == EnclosureStyle.Palisade
        assert op.cornerStyle == CornerStyle.Merlon
        # rng_seed = base_seed + 0xE101 (per design §10).
        assert op.rngSeed == (42 + 0xE101) & 0xFFFFFFFFFFFFFFFF
        # Polygon has 4 vertices in pixel coords.
        assert len(op.polygon.paths) == 4
        # No gates → empty list (or None, depending on builder).
        assert not op.gates

    def test_fortification_with_gate_emits_gate_entry(self) -> None:
        builder = self._builder()
        emit_site_enclosure(
            builder,
            polygon_tiles=[(0, 0), (8, 0), (8, 8), (0, 8)],
            style=EnclosureStyle.Fortification,
            gates=[(0, 0.5, 32.0)],  # one gate centered on edge 0
            base_seed=7,
            corner_style=CornerStyle.Diamond,
        )
        op = builder.ops[0].op
        assert op.style == EnclosureStyle.Fortification
        assert op.cornerStyle == CornerStyle.Diamond
        assert len(op.gates) == 1
        assert op.gates[0].edgeIdx == 0
        assert op.gates[0].tCenter == pytest.approx(0.5)
        assert op.gates[0].halfPx == pytest.approx(32.0)
        assert op.gates[0].style == GateStyle.Wood

    def test_too_few_vertices_no_op(self) -> None:
        builder = self._builder()
        emit_site_enclosure(
            builder,
            polygon_tiles=[(0, 0), (1, 0)],  # 2 verts — degenerate
            style=EnclosureStyle.Palisade,
            base_seed=0,
        )
        assert builder.ops == []


class TestEnclosureIRToSvg:
    def _build_buf(
        self,
        style: int = EnclosureStyle.Palisade,
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
            style=style,
            gates=gates,
            base_seed=seed,
            corner_style=corner_style,
        )
        return builder.finish()

    def test_palisade_svg_contains_circles(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(style=EnclosureStyle.Palisade)
        svg = ir_to_svg(buf)
        assert "<!-- layer.structural:" in svg
        # Palisade fill colour appears on every circle.
        assert 'fill="#8A5A2A"' in svg
        # Circles, not battlement rects.
        assert "<circle" in svg

    def test_fortification_svg_contains_battlements(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(style=EnclosureStyle.Fortification)
        svg = ir_to_svg(buf)
        # Crenel fill (black) and merlon fill (soft grey).
        assert 'fill="#D8D8D8"' in svg
        assert 'fill="#000000"' in svg
        # No palisade circles.
        assert 'fill="#8A5A2A"' not in svg

    def test_palisade_with_gate_emits_door_rect(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(
            style=EnclosureStyle.Palisade,
            gates=[(0, 0.5, 32.0)],
        )
        svg = ir_to_svg(buf)
        # Door rect width = PALISADE_DOOR_LENGTH_PX = 64.0.
        assert 'width="64.0"' in svg

    def test_fortification_diamond_corner_rotation(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(
            style=EnclosureStyle.Fortification,
            corner_style=CornerStyle.Diamond,
        )
        svg = ir_to_svg(buf)
        # Diamond corner uses rotate(45 ...).
        assert "rotate(45" in svg

    def test_fortification_merlon_corner_no_rotation(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf = self._build_buf(
            style=EnclosureStyle.Fortification,
            corner_style=CornerStyle.Merlon,
        )
        svg = ir_to_svg(buf)
        assert "rotate(45" not in svg

    def test_palisade_is_deterministic_per_seed(self) -> None:
        """Per-edge splitmix64(rng_seed + edge_idx) — same seed
        produces identical SVG, different seeds diverge."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        a = ir_to_svg(self._build_buf(seed=99))
        b = ir_to_svg(self._build_buf(seed=99))
        assert a == b
        c = ir_to_svg(self._build_buf(seed=100))
        assert a != c

    def test_per_edge_seed_isolation(self) -> None:
        """Adding a gate on one edge must NOT shift circle layout
        on other edges — per-edge palisade seeds are
        ``rng_seed + edge_idx``."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        buf_clean = self._build_buf(
            style=EnclosureStyle.Palisade, gates=None,
        )
        buf_gated = self._build_buf(
            style=EnclosureStyle.Palisade,
            gates=[(0, 0.5, 32.0)],
        )
        svg_clean = ir_to_svg(buf_clean)
        svg_gated = ir_to_svg(buf_gated)

        def _circles_on_edge_2(svg: str) -> list[str]:
            # Edge 2 runs along y == 12*CELL == 384 in the IR's
            # bare tile-pixel coords. That's the bottom side of
            # the rect; circles there all carry cy="384.0". The
            # outer translate(padding,padding) shifts the rendered
            # SVG by PADDING but doesn't affect the source coords.
            return [
                line for line in svg.split('<')
                if line.startswith('circle ') and 'cy="384.0"' in line
            ]
        clean_e2 = _circles_on_edge_2(svg_clean)
        gated_e2 = _circles_on_edge_2(svg_gated)
        assert clean_e2 == gated_e2 and clean_e2  # non-empty + identical


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

        Phase 1.12 added a parallel ExteriorWallOp emission so the
        legacy interior+exterior pair grew to interior + legacy
        exterior + new ExteriorWallOp. This test focuses on the
        legacy ops; :class:`TestEmitBuildingExteriorWallOp` pins the
        new-op contract.
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
            base_seed=42, building_index=0,
        )
        legacy_ops = [
            e for e in builder.ops
            if e.opType in (
                Op.Op.BuildingInteriorWallOp,
                Op.Op.BuildingExteriorWallOp,
            )
        ]
        # 1 interior + 1 legacy exterior; interior first.
        assert len(legacy_ops) == 2
        intr = legacy_ops[0].op
        assert intr.regionRef == "building.0"
        assert intr.material == InteriorWallMaterial.Stone
        ext = legacy_ops[1].op
        assert ext.regionRef == "building.0"
        assert ext.material == WallMaterial.Brick
        # rng_seed = base_seed + 0xBE71 + i.
        assert ext.rngSeed == (42 + 0xBE71 + 0) & 0xFFFFFFFFFFFFFFFF

    def test_dungeon_material_skips_exterior(self) -> None:
        """Buildings tagged `wall_material == "dungeon"` flow
        through the existing WallsAndFloorsOp pass instead of
        emitting a BuildingExteriorWallOp.

        Phase 1.12: ``wall_material == "dungeon"`` skips both the
        legacy and new exterior wall ops, leaving only the interior
        partition op.
        """
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
        # Only the interior op fires; both legacy + new exterior
        # ops skip for dungeon-walled buildings.
        assert len(builder.ops) == 1
        op = builder.ops[0].op
        assert op.regionRef == "building.0"

    def test_interior_edges_threaded_to_op(self) -> None:
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
        intr = builder.ops[0].op
        assert intr.material == InteriorWallMaterial.Wood
        assert len(intr.edges) == 1
        e = intr.edges[0]
        assert (e.ax, e.ay) == (3, 4)
        assert e.aCorner == TileCorner.NW
        assert e.bCorner == TileCorner.NE


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

    def test_brick_svg_uses_brick_palette(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(wall_material="brick"))
        # Brick fill / seam show up in the masonry rects.
        assert 'fill="#B4695A"' in svg
        assert 'stroke="#6A3A2A"' in svg

    def test_stone_svg_uses_stone_palette(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(wall_material="stone"))
        assert 'fill="#9A8E80"' in svg
        assert 'stroke="#4A3E35"' in svg

    def test_octagon_emits_diagonal_runs(self) -> None:
        """Octagon polygon → diagonal edges → masonry rects with
        rotate(...) transforms."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(
            wall_material="brick",
            shape=OctagonShape(),
            rect=Rect(2, 2, 9, 9),
        ))
        assert "rotate(" in svg

    def test_circle_emits_diagonal_runs(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(
            wall_material="brick",
            shape=CircleShape(),
            rect=Rect(2, 2, 8, 8),
        ))
        assert "rotate(" in svg

    def test_interior_walls_paint_lines_in_material_color(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(
            interior_wall_material="wood",
            interior_edges=[(3, 4, "north"), (4, 4, "north")],
        ))
        # Wood interior wall colour appears on at least one <line>.
        assert 'stroke="#7a4e2c"' in svg
        assert "<line" in svg

    def test_no_interior_edges_emits_no_lines(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(interior_edges=[]))
        # No interior-wall <line> elements; masonry uses <rect>.
        assert "<line" not in svg

    def test_deterministic_per_seed(self) -> None:
        from nhc.rendering.ir_to_svg import ir_to_svg
        a = ir_to_svg(self._build_buf(seed=99))
        b = ir_to_svg(self._build_buf(seed=99))
        assert a == b
        c = ir_to_svg(self._build_buf(seed=100))
        assert a != c

    def test_dungeon_material_paints_no_exterior(self) -> None:
        """Dungeon-material buildings emit a single
        BuildingInteriorWallOp; no masonry rects show up."""
        from nhc.rendering.ir_to_svg import ir_to_svg
        svg = ir_to_svg(self._build_buf(wall_material="dungeon"))
        # No brick/stone palette markers.
        assert 'fill="#B4695A"' not in svg
        assert 'fill="#9A8E80"' not in svg


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
        assert wop.outline is not None
        assert wop.outline.descriptorKind == OutlineKind.Polygon
        assert wop.outline.closed is True

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
        assert wop.outline.descriptorKind == OutlineKind.Polygon
        # OctagonShape footprint is 8-vertex per
        # _building_footprint_polygon_px.
        assert len(wop.outline.vertices) == 8

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
        outline_verts = [
            (v.x, v.y) for v in wall_ops[0].op.outline.vertices
        ]
        expected = [
            (float(x), float(y))
            for x, y in _building_footprint_polygon_px(b)
        ]
        assert outline_verts == expected, (
            "ExteriorWallOp outline must equal "
            "_building_footprint_polygon_px output verbatim"
        )

    def test_exterior_wall_op_lands_after_legacy_ops(self) -> None:
        """The new ExteriorWallOp lands AFTER both the legacy
        BuildingInteriorWallOp + BuildingExteriorWallOp entries.

        The current emit order is interior-then-exterior for the
        legacy ops (per design/map_ir.md §6.1); the new ExteriorWallOp
        appends after both so future consumer switches at 1.16+ can
        prefer the new op without rearranging ops[]. Mirrors the
        Phase 1.10 cave ExteriorWallOp post-WallsAndFloorsOp
        placement.
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

        op_types = [e.opType for e in builder.ops]
        legacy_ext_idx = op_types.index(Op.Op.BuildingExteriorWallOp)
        new_ext_idx = op_types.index(Op.Op.ExteriorWallOp)
        assert new_ext_idx > legacy_ext_idx, (
            "new ExteriorWallOp must land after the legacy "
            "BuildingExteriorWallOp in ops[]"
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
        cuts = wall_ops[0].op.outline.cuts or []
        assert cuts == [], (
            "stub level has no door tiles — cuts must be empty"
        )

    def test_legacy_building_exterior_wall_op_still_emitted(self) -> None:
        """Phase 1.12 ships parallel emission — the legacy
        BuildingExteriorWallOp keeps populating until 1.20 retires
        it. Pinning the parallel-emission contract guards against
        accidentally short-circuiting the legacy pass."""
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
            base_seed=42, building_index=0,
        )

        legacy_ops = [
            e for e in builder.ops
            if e.opType == Op.Op.BuildingExteriorWallOp
        ]
        new_ops = [
            e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
        ]
        assert len(legacy_ops) == 1, (
            "legacy BuildingExteriorWallOp must still ship"
        )
        assert len(new_ops) == 1, (
            "new ExteriorWallOp must ship alongside the legacy op"
        )
        # Both ops share the same building region.
        assert legacy_ops[0].op.regionRef == "building.0"

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
        cuts = wall_ops[0].op.outline.cuts or []
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
