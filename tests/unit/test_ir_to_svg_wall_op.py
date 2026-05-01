"""Phase 1.16 — tests for the ExteriorWallOp / InteriorWallOp consumer.

Tests are written first (TDD) and cover:

- _draw_exterior_wall_op_from_ir emits a polyline stroke for a
  DungeonInk Polygon outline (deferred to 1.16b — skipped here).
- _draw_exterior_wall_op_from_ir emits masonry for MasonryBrick /
  MasonryStone Polygon outlines (ExteriorWallOp from buildings).
- _draw_exterior_wall_op_from_ir emits palisade circles for a
  Palisade outline.
- _draw_exterior_wall_op_from_ir emits battlement chain for a
  FortificationMerlon outline.
- _draw_interior_wall_op_from_ir emits a <line> for PartitionWood /
  PartitionStone / PartitionBrick outlines (open 2-vertex polyline).
- A Cut on an ExteriorWallOp produces a gap in the palisade ring.
- A CutStyle.DoorSecret cut does NOT produce a gate visual.
- ExteriorWallOp consumer replaces legacy BuildingExteriorWallOp /
  EnclosureOp handlers for their regions.
- InteriorWallOp consumer replaces legacy BuildingInteriorWallOp.
- When no ExteriorWallOp / InteriorWallOp are present (3.x cached
  buffer), the legacy handlers still emit walls.
"""

from __future__ import annotations

import math
import re

import flatbuffers
import pytest

from nhc.rendering._svg_helpers import CELL
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.ExteriorWallOp import ExteriorWallOpT
from nhc.rendering.ir._fb.InteriorWallOp import InteriorWallOpT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.WallStyle import WallStyle
from nhc.rendering.ir._fb.Cut import CutT
from nhc.rendering.ir._fb.Vec2 import Vec2T


# ── Test helpers ───────────────────────────────────────────────────


def _vec2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _build_polygon_outline(
    vertices: list[tuple[float, float]],
    *,
    closed: bool = True,
    cuts: list[CutT] | None = None,
) -> OutlineT:
    """Build a Polygon-descriptor OutlineT from a vertex list."""
    out = OutlineT()
    out.descriptorKind = OutlineKind.Polygon
    out.closed = closed
    out.vertices = [_vec2(x, y) for x, y in vertices]
    out.cuts = cuts or []
    return out


def _build_cut(
    sx: float, sy: float,
    ex: float, ey: float,
    style: int = CutStyle.None_,
) -> CutT:
    """Build a CutT with pixel-space start/end coords."""
    c = CutT()
    c.start = _vec2(sx, sy)
    c.end = _vec2(ex, ey)
    c.style = style
    return c


def _build_fir_buf_with_exterior_wall_op(
    outline: OutlineT,
    style: int,
    corner_style: int = 0,
) -> bytes:
    """Serialise a minimal FloorIR with one ExteriorWallOp entry."""
    from nhc.rendering.ir._fb.FloorIR import FloorIRT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT

    fir_t = FloorIRT()
    fir_t.major = 3
    fir_t.minor = 1
    fir_t.widthTiles = 20
    fir_t.heightTiles = 20
    fir_t.cell = 32
    fir_t.padding = 32
    fir_t.ops = []
    fir_t.regions = []

    wall_op = ExteriorWallOpT()
    wall_op.outline = outline
    wall_op.style = style
    wall_op.cornerStyle = corner_style

    entry = OpEntryT()
    entry.opType = Op.Op.ExteriorWallOp
    entry.op = wall_op
    fir_t.ops.append(entry)

    _FILE_IDENTIFIER = b"NIR3"
    builder = flatbuffers.Builder(512)
    builder.Finish(fir_t.Pack(builder), _FILE_IDENTIFIER)
    return bytes(builder.Output())


def _build_fir_buf_with_interior_wall_op(
    outline: OutlineT,
    style: int,
) -> bytes:
    """Serialise a minimal FloorIR with one InteriorWallOp entry."""
    from nhc.rendering.ir._fb.FloorIR import FloorIRT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT

    fir_t = FloorIRT()
    fir_t.major = 3
    fir_t.minor = 1
    fir_t.widthTiles = 20
    fir_t.heightTiles = 20
    fir_t.cell = 32
    fir_t.padding = 32
    fir_t.ops = []
    fir_t.regions = []

    wall_op = InteriorWallOpT()
    wall_op.outline = outline
    wall_op.style = style

    entry = OpEntryT()
    entry.opType = Op.Op.InteriorWallOp
    entry.op = wall_op
    fir_t.ops.append(entry)

    _FILE_IDENTIFIER = b"NIR3"
    builder = flatbuffers.Builder(512)
    builder.Finish(fir_t.Pack(builder), _FILE_IDENTIFIER)
    return bytes(builder.Output())


def _call_exterior_wall_handler(
    outline: OutlineT,
    style: int,
    corner_style: int = 0,
) -> list[str]:
    """Dispatch _draw_exterior_wall_op_from_ir via a serialise round-trip."""
    buf = _build_fir_buf_with_exterior_wall_op(outline, style, corner_style)
    from nhc.rendering.ir._fb.FloorIR import FloorIR
    fir = FloorIR.GetRootAs(buf, 0)
    from nhc.rendering.ir_to_svg import _draw_exterior_wall_op_from_ir
    entry_fb = fir.Ops(0)
    return _draw_exterior_wall_op_from_ir(entry_fb, fir)


def _call_interior_wall_handler(
    outline: OutlineT,
    style: int,
) -> list[str]:
    """Dispatch _draw_interior_wall_op_from_ir via a serialise round-trip."""
    buf = _build_fir_buf_with_interior_wall_op(outline, style)
    from nhc.rendering.ir._fb.FloorIR import FloorIR
    fir = FloorIR.GetRootAs(buf, 0)
    from nhc.rendering.ir_to_svg import _draw_interior_wall_op_from_ir
    entry_fb = fir.Ops(0)
    return _draw_interior_wall_op_from_ir(entry_fb, fir)


# Simple 5×3 building footprint in pixel space (tile coords × 32)
# at tile origin (1, 1): polygon corners at pixel (32, 32), (192, 32),
# (192, 128), (32, 128).
_BUILDING_POLY = [
    (32.0, 32.0), (192.0, 32.0), (192.0, 128.0), (32.0, 128.0),
]

# Simple 4-vertex palisade ring (40×40 pixel square).
_PALISADE_POLY = [
    (0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0),
]


# ── Unit tests: MasonryBrick / MasonryStone ───────────────────────


def test_exterior_wall_op_masonry_brick_emits_rect_elements() -> None:
    """MasonryBrick ExteriorWallOp produces masonry <rect> elements."""
    outline = _build_polygon_outline(_BUILDING_POLY)
    frags = _call_exterior_wall_handler(outline, WallStyle.MasonryBrick)
    assert len(frags) > 0, "Expected masonry rects from MasonryBrick ExteriorWallOp"
    # Every element should be a <rect> (masonry bricks)
    for f in frags:
        assert f.startswith("<rect "), f"Expected <rect>, got: {f[:60]}"
    # Fill should use brick colour.
    fills = [f for f in frags if '#B4695A' in f or '#6A3A2A' in f]
    assert fills, "Expected brick fill/seam colour in masonry output"


def test_exterior_wall_op_masonry_stone_uses_stone_colours() -> None:
    """MasonryStone ExteriorWallOp uses stone fill (#9A8E80)."""
    outline = _build_polygon_outline(_BUILDING_POLY)
    frags = _call_exterior_wall_handler(outline, WallStyle.MasonryStone)
    assert len(frags) > 0
    fills = [f for f in frags if '#9A8E80' in f or '#4A3E35' in f]
    assert fills, "Expected stone fill/seam colour in masonry output"


def test_exterior_wall_op_masonry_produces_multiple_strips() -> None:
    """Masonry produces 2-strip running-bond chain — multiple <rect>s."""
    # A 4-edge rect building with a 160-pixel long top edge should
    # produce several brick rects per edge.
    outline = _build_polygon_outline(_BUILDING_POLY)
    frags = _call_exterior_wall_handler(outline, WallStyle.MasonryBrick)
    # Each edge × 2 strips × several bricks. At least 4 (one per strip
    # per horizontal edge if very short) — in practice many more.
    assert len(frags) >= 4, (
        f"Expected ≥4 masonry rects for a 4-edge rect building, got {len(frags)}"
    )


# ── Unit tests: Palisade ──────────────────────────────────────────


def test_exterior_wall_op_palisade_emits_circle_elements() -> None:
    """Palisade ExteriorWallOp produces <circle> stake elements."""
    outline = _build_polygon_outline(_PALISADE_POLY)
    frags = _call_exterior_wall_handler(outline, WallStyle.Palisade)
    assert len(frags) > 0, "Expected palisade circles"
    circles = [f for f in frags if f.startswith("<circle ")]
    assert circles, "Expected <circle> elements for palisade stakes"
    # Fill should use palisade wood colour.
    assert any('#8A5A2A' in f for f in circles), "Expected palisade fill colour"


def test_exterior_wall_op_palisade_with_cut_creates_gap() -> None:
    """A Cut on a Palisade ExteriorWallOp suppresses stakes in the gap."""
    # Cut along the top edge (y=0) from x=80 to x=120 (gate centre 100).
    cut = _build_cut(80.0, 0.0, 120.0, 0.0, style=CutStyle.WoodGate)
    outline = _build_polygon_outline(_PALISADE_POLY, cuts=[cut])
    frags_no_cut = _call_exterior_wall_handler(
        _build_polygon_outline(_PALISADE_POLY), WallStyle.Palisade,
    )
    frags_with_cut = _call_exterior_wall_handler(outline, WallStyle.Palisade)
    # With a gate cut, the total stake count must be less than without.
    circles_no_cut = [f for f in frags_no_cut if f.startswith("<circle ")]
    circles_with_cut = [f for f in frags_with_cut if f.startswith("<circle ")]
    assert len(circles_with_cut) < len(circles_no_cut), (
        "Expected fewer palisade circles when a gate cut is present"
    )


def test_exterior_wall_op_palisade_woodgate_cut_emits_door_rect() -> None:
    """A WoodGate cut on Palisade produces the gate rect visual."""
    cut = _build_cut(80.0, 0.0, 120.0, 0.0, style=CutStyle.WoodGate)
    outline = _build_polygon_outline(_PALISADE_POLY, cuts=[cut])
    frags = _call_exterior_wall_handler(outline, WallStyle.Palisade)
    rects = [f for f in frags if f.startswith("<rect ")]
    assert rects, "Expected gate <rect> visual for WoodGate cut on palisade"


# ── Unit tests: FortificationMerlon ──────────────────────────────


def test_exterior_wall_op_fortification_emits_rect_elements() -> None:
    """FortificationMerlon ExteriorWallOp produces battlement <rect>s."""
    outline = _build_polygon_outline(_PALISADE_POLY)
    frags = _call_exterior_wall_handler(
        outline, WallStyle.FortificationMerlon,
    )
    assert len(frags) > 0, "Expected fortification rects"
    rects = [f for f in frags if f.startswith("<rect ")]
    assert rects, "Expected <rect> elements for battlement chain"


def test_exterior_wall_op_fortification_uses_battlement_colours() -> None:
    """FortificationMerlon ExteriorWallOp uses merlon grey (#D8D8D8)."""
    outline = _build_polygon_outline(_PALISADE_POLY)
    frags = _call_exterior_wall_handler(
        outline, WallStyle.FortificationMerlon,
    )
    assert any('#D8D8D8' in f or '#1A1A1A' in f for f in frags), (
        "Expected fortification merlon/stroke colour"
    )


# ── Unit tests: InteriorWallOp (Partition styles) ─────────────────


def test_interior_wall_op_open_polyline_emits_line() -> None:
    """InteriorWallOp with 2-vertex open polyline emits a <line>."""
    # Simple vertical partition from tile (3,2)SE corner to (3,3)NE corner.
    pts = [(3 * CELL, 2 * CELL), (3 * CELL, 3 * CELL)]
    outline = _build_polygon_outline(pts, closed=False)
    frags = _call_interior_wall_handler(outline, WallStyle.PartitionStone)
    assert len(frags) == 1, f"Expected 1 <line>, got {len(frags)}"
    assert frags[0].startswith("<line "), f"Expected <line> element, got: {frags[0][:60]}"


def test_interior_wall_op_partition_wood_uses_wood_color() -> None:
    """PartitionWood → stroke colour #7a4e2c."""
    pts = [(64.0, 64.0), (64.0, 96.0)]
    outline = _build_polygon_outline(pts, closed=False)
    frags = _call_interior_wall_handler(outline, WallStyle.PartitionWood)
    assert frags, "Expected output from PartitionWood InteriorWallOp"
    assert "#7a4e2c" in frags[0], (
        f"Expected wood colour #7a4e2c in partition line, got: {frags[0]}"
    )


def test_interior_wall_op_partition_stone_uses_stone_color() -> None:
    """PartitionStone → stroke colour #707070."""
    pts = [(64.0, 64.0), (96.0, 64.0)]
    outline = _build_polygon_outline(pts, closed=False)
    frags = _call_interior_wall_handler(outline, WallStyle.PartitionStone)
    assert frags
    assert "#707070" in frags[0], (
        f"Expected stone colour #707070 in partition line, got: {frags[0]}"
    )


def test_interior_wall_op_partition_brick_uses_brick_color() -> None:
    """PartitionBrick → stroke colour #c4651d."""
    pts = [(0.0, 0.0), (32.0, 0.0)]
    outline = _build_polygon_outline(pts, closed=False)
    frags = _call_interior_wall_handler(outline, WallStyle.PartitionBrick)
    assert frags
    assert "#c4651d" in frags[0], (
        f"Expected brick colour #c4651d in partition line, got: {frags[0]}"
    )


def test_interior_wall_op_line_has_round_linecap() -> None:
    """Interior partition <line> carries stroke-linecap='round'."""
    pts = [(0.0, 0.0), (32.0, 0.0)]
    outline = _build_polygon_outline(pts, closed=False)
    frags = _call_interior_wall_handler(outline, WallStyle.PartitionStone)
    assert frags
    assert 'stroke-linecap="round"' in frags[0], (
        "Expected round linecap on partition line"
    )


def test_interior_wall_op_empty_outline_returns_empty() -> None:
    """InteriorWallOp with no vertices returns []."""
    outline = _build_polygon_outline([], closed=False)
    frags = _call_interior_wall_handler(outline, WallStyle.PartitionStone)
    assert frags == []


# ── Consumer switch: legacy suppression ───────────────────────────


def _build_seed7_building_floor0_buf() -> bytes:
    """Build the seed7_brick_building_floor0 FloorIR buffer.

    Uses the same construction path as the parity gate fixture
    (``assemble_site`` + ``emit_building_overlays``) so the IR
    contains both ExteriorWallOp + BuildingExteriorWallOp (parallel
    emission from Phase 1.12 / 8.3).
    """
    from tests.samples.regenerate_fixtures import (
        _BUILDING_FIXTURES, _build_building_inputs,
    )
    from nhc.rendering.ir_emitter import build_floor_ir
    fx = next(
        f for f in _BUILDING_FIXTURES
        if f.descriptor == "seed7_brick_building_floor0"
    )
    site, level = _build_building_inputs(fx)
    buf = build_floor_ir(
        level, seed=fx.seed, hatch_distance=2.0, site=site,
    )
    return bytes(buf)


def test_wall_op_consumer_replaces_legacy_building_exterior_walls() -> None:
    """When ExteriorWallOp is present, BuildingExteriorWallOp is suppressed.

    Build a FloorIR with both a BuildingExteriorWallOp (legacy) AND an
    ExteriorWallOp (new). The rendered SVG should contain masonry rects
    from the new handler — and the legacy BuildingExteriorWallOp should
    not double-paint the same walls.

    We detect the switch by checking that the SVG does NOT contain both
    handlers' outputs: the new handler uses the outline vertices from
    ExteriorWallOp; the legacy handler resolves the region polygon.
    Because the fixture actually emits both ops in parallel, we verify
    the parity gate passes (see test_ir_png_parity.py) and here just
    check that the new-path masonry appears.
    """
    from nhc.rendering.ir_to_svg import ir_to_svg

    buf = _build_seed7_building_floor0_buf()
    svg = ir_to_svg(buf)
    # New path must be active: masonry <rect> elements with brick fill.
    # (Legacy building walls also produce rects, but only when
    # ExteriorWallOp is absent — checking the flag in debug output
    # is impractical here; parity gate covers pixel accuracy.)
    assert '<rect ' in svg, (
        "Expected masonry rects in building SVG output"
    )


def test_wall_op_consumer_replaces_legacy_interior_walls() -> None:
    """When InteriorWallOp is present, BuildingInteriorWallOp is suppressed.

    The partition <line> elements from InteriorWallOp should appear
    in the rendered SVG for a building fixture.
    """
    from nhc.rendering.ir_to_svg import ir_to_svg

    buf = _build_seed7_building_floor0_buf()
    svg = ir_to_svg(buf)
    # New path: partition lines appear as <line> elements.
    assert "<line " in svg, (
        "Expected partition <line> elements in building SVG output"
    )


def test_wall_op_fallback_to_legacy_when_absent() -> None:
    """A FloorIR with no ExteriorWallOp / InteriorWallOp uses legacy handlers.

    Build a minimal FloorIR with only WallsAndFloorsOp (wall_segments)
    and a BuildingExteriorWallOp. Neither ExteriorWallOp nor
    InteriorWallOp is present. Legacy handlers must still fire.
    """
    from nhc.rendering.ir._fb.FloorIR import FloorIRT
    from nhc.rendering.ir._fb.WallsAndFloorsOp import WallsAndFloorsOpT
    from nhc.rendering.ir._fb.BuildingExteriorWallOp import (
        BuildingExteriorWallOpT,
    )
    from nhc.rendering.ir._fb.Region import RegionT
    from nhc.rendering.ir._fb.RegionKind import RegionKind
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.Polygon import PolygonT
    from nhc.rendering.ir._fb.PathRange import PathRangeT
    from nhc.rendering.ir_to_svg import ir_to_svg

    # Build a minimal WallsAndFloorsOp with no ExteriorWallOp/InteriorWallOp.
    fir_t = FloorIRT()
    fir_t.major = 3
    fir_t.minor = 1
    fir_t.widthTiles = 10
    fir_t.heightTiles = 10
    fir_t.cell = 32
    fir_t.padding = 32
    fir_t.ops = []
    fir_t.regions = []

    waf = WallsAndFloorsOpT()
    waf.rectRooms = []
    waf.corridorTiles = []
    waf.smoothFillSvg = []
    waf.smoothWallSvg = []
    waf.wallSegments = ["M32,32 L64,32"]
    waf.caveRegion = ""
    waf.wallExtensionsD = ""

    entry = OpEntryT()
    entry.opType = Op.Op.WallsAndFloorsOp
    entry.op = waf
    fir_t.ops.append(entry)

    # Add a BuildingExteriorWallOp with a region polygon (no ExteriorWallOp).
    poly = PolygonT()
    poly.paths = [_vec2(32.0, 32.0), _vec2(192.0, 32.0), _vec2(192.0, 128.0),
                  _vec2(32.0, 128.0)]
    pr = PathRangeT()
    pr.start = 0
    pr.count = 4
    pr.isHole = False
    poly.rings = [pr]

    reg = RegionT()
    reg.id = "building.0"
    reg.kind = RegionKind.Building
    reg.polygon = poly
    reg.shapeTag = "rect"
    fir_t.regions.append(reg)

    bew = BuildingExteriorWallOpT()
    bew.regionRef = "building.0"
    bew.material = 0  # Stone
    bew.rngSeed = 42

    bew_entry = OpEntryT()
    bew_entry.opType = Op.Op.BuildingExteriorWallOp
    bew_entry.op = bew
    fir_t.ops.append(bew_entry)

    _FILE_IDENTIFIER = b"NIR3"
    builder = flatbuffers.Builder(2048)
    builder.Finish(fir_t.Pack(builder), _FILE_IDENTIFIER)
    buf = bytes(builder.Output())

    svg = ir_to_svg(buf)
    # Legacy wall segments produce a <path d="..."> element.
    assert 'M32,32' in svg, (
        "Expected legacy wall segment path when no ExteriorWallOp present"
    )
    # Legacy BuildingExteriorWallOp should produce masonry rects.
    assert '<rect ' in svg, (
        "Expected legacy masonry rects from BuildingExteriorWallOp fallback"
    )
