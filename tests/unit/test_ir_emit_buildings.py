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
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir_emitter import (
    FloorIRBuilder,
    _building_footprint_polygon_px,
    _CIRCLE_FOOTPRINT_VERTICES,
    _ROOF_TINTS,
    _collect_building_footprint_mask,
    _point_in_polygon,
    emit_building_regions,
    emit_building_roofs,
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
    def test_rect_returns_4_pixel_corners(self) -> None:
        b = _StubBuilding(RectShape(), Rect(2, 3, 5, 4))
        poly = _building_footprint_polygon_px(b)
        assert len(poly) == 4
        # Top-left corner.
        x0, y0 = poly[0]
        assert x0 == PADDING + 2 * CELL
        assert y0 == PADDING + 3 * CELL
        # Bottom-right corner is the third vertex (CW from top-left).
        x2, y2 = poly[2]
        assert x2 == PADDING + (2 + 5) * CELL
        assert y2 == PADDING + (3 + 4) * CELL

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
        # Centre at PADDING + (rect_x + width/2) * CELL.
        cx_expected = PADDING + 5.0 * CELL
        cy_expected = PADDING + 5.0 * CELL
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
        assert fir.Major() == 2
        # RoofOp landed at MINOR=1; later additive bumps must keep it.
        assert fir.Minor() >= 1
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
        from nhc.rendering.ir._fb.RoofOp import RoofOpT
        from nhc.rendering.ir._fb.RoofStyle import RoofStyle
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
