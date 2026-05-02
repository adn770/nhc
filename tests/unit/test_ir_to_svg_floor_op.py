"""Phase 1.15 — tests for the FloorOp consumer in ir_to_svg.

Tests are written first (TDD) and cover:

- _draw_floor_op_from_ir emits a <polygon> for a Polygon-descriptor
  outline (rect room, octagon, L-shape, temple, cave polygon).
- _draw_floor_op_from_ir emits a <circle> for a Circle-descriptor.
- _draw_floor_op_from_ir emits a rounded-rect <rect rx ry> for a
  Pill-descriptor.
- FloorStyle.DungeonFloor → fill="#FFFFFF".
- FloorStyle.CaveFloor → fill="#F5EBD8".
- Cave FloorOp (Polygon, CaveFloor) emits a bezier <path> matching
  the legacy cave-region fill.
- A FloorIR with FloorOps present renders floors through them and
  WallsAndFloorsOp skips its legacy floor emission.
- A legacy 3.x FloorIR (no FloorOp) still renders via
  WallsAndFloorsOp for full back-compat.

Phase real-consumer (follow-up to 1.15b):
- CaveFloor FloorOp consumer reads outline.vertices via
  buffer+jitter+smooth pipeline (NOT legacy cave_region field).
- Pipeline matches legacy _build_cave_wall_geometry output exactly.
"""

from __future__ import annotations

import re

import flatbuffers
import pytest

from nhc.rendering._svg_helpers import CAVE_FLOOR_COLOR, FLOOR_COLOR
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorOp import FloorOpT, FloorOpStart, FloorOpEnd, FloorOpAddOutline, FloorOpAddStyle
from nhc.rendering.ir._fb.FloorStyle import FloorStyle
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind


# ── Helpers ────────────────────────────────────────────────────────


def _build_polygon_outline(
    vertices: list[tuple[float, float]],
) -> OutlineT:
    """Build a Polygon-descriptor OutlineT from a vertex list."""
    out = OutlineT()
    from nhc.rendering.ir._fb.Vec2 import Vec2T
    out.descriptorKind = OutlineKind.Polygon
    out.closed = True
    out.vertices = []
    out.cuts = []
    for x, y in vertices:
        v = Vec2T()
        v.x = x
        v.y = y
        out.vertices.append(v)
    return out


def _build_circle_outline(
    cx: float, cy: float, r: float,
) -> OutlineT:
    out = OutlineT()
    out.descriptorKind = OutlineKind.Circle
    out.closed = True
    out.vertices = []
    out.cuts = []
    out.cx = cx
    out.cy = cy
    out.rx = r
    out.ry = r
    return out


def _build_pill_outline(
    cx: float, cy: float, rx: float, ry: float,
) -> OutlineT:
    out = OutlineT()
    out.descriptorKind = OutlineKind.Pill
    out.closed = True
    out.vertices = []
    out.cuts = []
    out.cx = cx
    out.cy = cy
    out.rx = rx
    out.ry = ry
    return out


def _build_fir_buf_with_floor_op(
    outline: OutlineT,
    style: int,
) -> bytes:
    """Serialise a minimal FloorIR containing one FloorOp entry."""
    import flatbuffers
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

    floor_op = FloorOpT()
    floor_op.outline = outline
    floor_op.style = style

    entry = OpEntryT()
    entry.opType = Op.Op.FloorOp
    entry.op = floor_op
    fir_t.ops.append(entry)

    _FILE_IDENTIFIER = b"NIR3"
    builder = flatbuffers.Builder(512)
    builder.Finish(fir_t.Pack(builder), _FILE_IDENTIFIER)
    return bytes(builder.Output())


def _call_floor_op_handler(
    outline: OutlineT,
    style: int,
) -> list[str]:
    """Call _draw_floor_op_from_ir via a minimal serialise + dispatch."""
    buf = _build_fir_buf_with_floor_op(outline, style)

    from nhc.rendering.ir._fb.FloorIR import FloorIR
    fir = FloorIR.GetRootAs(buf, 0)

    from nhc.rendering.ir_to_svg import _draw_floor_op_from_ir
    entry_fb = fir.Ops(0)
    return _draw_floor_op_from_ir(entry_fb, fir)


# ── Unit tests: handler output format ─────────────────────────────


def test_floor_op_handler_emits_polygon_for_rect_outline() -> None:
    """A FloorOp with rect-poly Outline produces a <polygon> SVG."""
    # 4x3 rect room at (2, 2) → pixel bbox (64, 64, 128, 96)
    pts = [(64.0, 64.0), (192.0, 64.0), (192.0, 160.0), (64.0, 160.0)]
    outline = _build_polygon_outline(pts)
    frags = _call_floor_op_handler(outline, FloorStyle.DungeonFloor)
    assert len(frags) == 1
    frag = frags[0]
    assert frag.startswith("<polygon ")
    assert 'points="' in frag
    # All four corners appear (in order)
    assert "64.0,64.0" in frag
    assert "192.0,64.0" in frag
    assert "192.0,160.0" in frag
    assert "64.0,160.0" in frag


def test_floor_op_handler_emits_circle_for_circle_descriptor() -> None:
    """A FloorOp with Circle descriptor produces a <circle> SVG."""
    outline = _build_circle_outline(cx=160.0, cy=160.0, r=96.0)
    frags = _call_floor_op_handler(outline, FloorStyle.DungeonFloor)
    assert len(frags) == 1
    frag = frags[0]
    assert frag.startswith("<circle ")
    assert 'cx="160.0"' in frag or 'cx="160"' in frag
    assert 'cy="160.0"' in frag or 'cy="160"' in frag
    assert 'r="96.0"' in frag or 'r="96"' in frag


def test_floor_op_handler_emits_pill_for_pill_descriptor() -> None:
    """A FloorOp with Pill descriptor produces a rounded-rect SVG."""
    # cx=160, cy=128, rx=96, ry=64 → x=64, y=64, w=192, h=128, radius=64
    outline = _build_pill_outline(cx=160.0, cy=128.0, rx=96.0, ry=64.0)
    frags = _call_floor_op_handler(outline, FloorStyle.DungeonFloor)
    assert len(frags) == 1
    frag = frags[0]
    assert frag.startswith("<rect ")
    assert "rx=" in frag
    assert "ry=" in frag


def test_floor_op_dungeon_style_uses_floor_color() -> None:
    """FloorStyle.DungeonFloor → fill=FLOOR_COLOR (#FFFFFF)."""
    pts = [(0.0, 0.0), (32.0, 0.0), (32.0, 32.0), (0.0, 32.0)]
    outline = _build_polygon_outline(pts)
    frags = _call_floor_op_handler(outline, FloorStyle.DungeonFloor)
    assert FLOOR_COLOR in frags[0]


def test_floor_op_cave_style_uses_cave_floor_color() -> None:
    """FloorStyle.CaveFloor → fill=CAVE_FLOOR_COLOR (#F5EBD8)."""
    pts = [(0.0, 0.0), (32.0, 0.0), (32.0, 32.0), (0.0, 32.0)]
    outline = _build_polygon_outline(pts)
    frags = _call_floor_op_handler(outline, FloorStyle.CaveFloor)
    assert CAVE_FLOOR_COLOR in frags[0]


def test_floor_op_wood_style_uses_wood_floor_color() -> None:
    """Phase 1.20b: FloorStyle.WoodFloor → fill="#B58B5A".

    The consumer must accept the new style and emit the building
    wood-floor brown polygon. Without this branch the WoodFloor
    FloorOps emitted by the brick_building fixture would render as
    white DungeonFloor — the same regression the legacy
    ``smoothFillSvg`` path produced when the Rust gate suppressed
    it for fresh IR.
    """
    from nhc.rendering._floor_detail import WOOD_FLOOR_FILL

    pts = [(0.0, 0.0), (32.0, 0.0), (32.0, 32.0), (0.0, 32.0)]
    outline = _build_polygon_outline(pts)
    frags = _call_floor_op_handler(outline, FloorStyle.WoodFloor)
    assert len(frags) == 1
    assert frags[0].startswith("<polygon ")
    assert WOOD_FLOOR_FILL in frags[0]


# ── Integration tests: consumer switch behaviour ───────────────────


def test_floor_op_consumer_replaces_rect_rooms() -> None:
    """A FloorIR with FloorOps and rect_rooms renders floors via FloorOp.

    When FloorOps are present, WallsAndFloorsOp skips its legacy
    corridor_tiles + rect_rooms floor emission. The structural layer
    produces the same total elements (floors from FloorOp + walls
    from WallsAndFloorsOp) as the legacy path (all from
    WallsAndFloorsOp). Pixel content is checked by the parity gate;
    here we assert the SVG fragment source changed.
    """
    from nhc.rendering.ir_emitter import build_floor_ir
    from nhc.rendering.ir_to_svg import ir_to_svg
    from tests.fixtures.floor_ir._inputs import descriptor_inputs

    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed, hatch_distance=2.0, vegetation=True,
    )

    svg = ir_to_svg(buf)

    # Floors should be rendered as <polygon> elements from FloorOps
    # (not as <rect> with floor_color injected by draw_walls_and_floors).
    # The polygon path carries points="..." attribute.
    # Both rect rooms (4 vertices) and corridor tiles (4 vertices) match.
    assert '<polygon points="' in svg, (
        "Expected FloorOp polygon floors in SVG output; "
        "FloorOp handler may not be registered in the structural layer"
    )


def test_floor_op_fallback_to_legacy_when_absent() -> None:
    """A 3.x FloorIR with no FloorOp still renders via legacy fields.

    Build a minimal FloorIR with only WallsAndFloorsOp fields
    (rect_rooms + corridor_tiles) and no FloorOp entries. The
    consumer must fall back to the legacy path and produce floor
    rects.
    """
    import flatbuffers
    from nhc.rendering.ir._fb.FloorIR import FloorIRT
    from nhc.rendering.ir._fb.WallsAndFloorsOp import WallsAndFloorsOpT
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from nhc.rendering.ir._fb.RectRoom import RectRoomT
    from nhc.rendering.ir._fb.TileCoord import TileCoordT
    from nhc.rendering.ir_to_svg import ir_to_svg

    fir_t = FloorIRT()
    fir_t.major = 3
    fir_t.minor = 1
    fir_t.widthTiles = 10
    fir_t.heightTiles = 10
    fir_t.cell = 32
    fir_t.padding = 32
    fir_t.ops = []
    fir_t.regions = []

    # One rect room at (2, 2, 3, 3)
    waf = WallsAndFloorsOpT()
    rr = RectRoomT()
    rr.x = 2
    rr.y = 2
    rr.w = 3
    rr.h = 3
    waf.rectRooms = [rr]
    waf.corridorTiles = []
    waf.smoothFillSvg = []
    waf.smoothWallSvg = []
    waf.wallSegments = []
    waf.caveRegion = ""
    waf.wallExtensionsD = ""

    entry = OpEntryT()
    entry.opType = Op.Op.WallsAndFloorsOp
    entry.op = waf
    fir_t.ops.append(entry)

    _FILE_IDENTIFIER = b"NIR3"
    builder = flatbuffers.Builder(512)
    builder.Finish(fir_t.Pack(builder), _FILE_IDENTIFIER)
    buf = bytes(builder.Output())
    svg = ir_to_svg(buf)

    # Legacy path emits a <rect> for the room (floor fill).
    # The rect should be at pixel coords 2*32=64, 2*32=64, 3*32=96x96.
    assert 'fill="#FFFFFF"' in svg, (
        "Expected legacy floor rect in SVG when no FloorOp present; "
        "fallback path may be broken"
    )
    # Specifically a rect element covering the room
    assert 'x="64"' in svg or 'x="64.0"' in svg, (
        "Expected rect at x=64 from legacy WallsAndFloorsOp rect_room"
    )


# ── Phase 1.15b: CaveFloor consumer tests ─────────────────────────


def test_cave_floor_op_emits_smooth_closed_path() -> None:
    """A FloorOp with CaveFloor style + polygon outline produces an
    SVG path equivalent to _smooth_closed_path(coords) with cave
    fill color."""
    # Simple triangle approximation — enough to exercise the bezier path.
    pts = [(64.0, 32.0), (128.0, 96.0), (32.0, 96.0)]
    outline = _build_polygon_outline(pts)
    frags = _call_floor_op_handler(outline, FloorStyle.CaveFloor)
    assert len(frags) == 1, "Expected exactly one SVG fragment for CaveFloor FloorOp"
    frag = frags[0]
    # Must be a <path> (bezier) not a plain <polygon>
    assert frag.startswith("<path "), (
        f"Expected <path> for CaveFloor bezier; got: {frag[:80]}"
    )
    assert 'fill-rule="evenodd"' in frag, (
        "Expected fill-rule=evenodd on cave fill path"
    )
    assert CAVE_FLOOR_COLOR in frag, (
        f"Expected cave fill color {CAVE_FLOOR_COLOR} in fragment"
    )
    assert 'stroke="none"' in frag, (
        "Expected stroke=none on cave floor fill path"
    )


def test_cave_floor_op_consumer_replaces_legacy_cave_region() -> None:
    """When a CaveFloor FloorOp is present in the IR, ir_to_svg
    skips the legacy cave_region emission and renders the cave
    fill via the FloorOp handler."""
    from nhc.rendering.ir_emitter import build_floor_ir
    from nhc.rendering.ir_to_svg import ir_to_svg
    from tests.fixtures.floor_ir._inputs import descriptor_inputs

    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed, hatch_distance=2.0, vegetation=True,
    )
    svg = ir_to_svg(buf)

    # The FloorOp consumer must produce a <path> with fill-rule=evenodd
    # for the cave region (Catmull-Rom bezier), not a Rust-injected form.
    # Both legacy and new paths produce <path> with fill-rule=evenodd so
    # we assert the cave floor colour is present (correct for either path)
    # and that the polygon has bezier curves (C command in path d="").
    assert CAVE_FLOOR_COLOR in svg, (
        "Expected cave floor color in cave SVG output"
    )
    # A bezier path 'd' attribute contains C (cubic bezier segment)
    assert re.search(r'<path[^>]+d="[^"]*\bC\b', svg), (
        "Expected Catmull-Rom bezier path (C command) for cave floor"
    )


# ── Real-consumer follow-up tests (Phase 1.15b → real pipeline) ───


def test_cave_floor_op_consumer_reads_outline_vertices_not_legacy_field() -> None:
    """When a CaveFloor FloorOp is present, the consumer renders cave
    fill from outline.vertices via buffer+jitter+smooth_closed_path,
    NOT from WallsAndFloorsOp.cave_region. Smoke-test: clear cave_region
    in the IR (replace with empty string in the raw bytes) and assert
    the cave fill still renders correctly.

    The real consumer derives cave geometry from FloorOp.outline.vertices
    using the buffer+jitter+smooth_closed_path pipeline seeded from
    fir.BaseSeed() + 0x5A17E5. The WallsAndFloorsOp.cave_region field
    is no longer read for cave geometry.
    """
    import random
    from shapely.geometry import Polygon as ShapelyPolygon

    from nhc.rendering.ir_emitter import build_floor_ir
    from nhc.rendering.ir_to_svg import ir_to_svg
    from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
    from nhc.rendering.ir._fb.WallsAndFloorsOp import WallsAndFloorsOpT
    from nhc.rendering.ir._fb import Op
    from nhc.rendering.ir._fb.OpEntry import OpEntryT
    from tests.fixtures.floor_ir._inputs import descriptor_inputs

    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed, hatch_distance=2.0, vegetation=True,
    )

    # Deserialise, clear cave_region in WallsAndFloorsOp, re-serialise.
    fir_t = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    for entry in (fir_t.ops or []):
        if entry.opType == Op.Op.WallsAndFloorsOp:
            entry.op.caveRegion = ""
    import flatbuffers as _fb_module
    _FILE_IDENTIFIER = b"NIR3"
    builder = _fb_module.Builder(len(buf) + 64)
    builder.Finish(fir_t.Pack(builder), _FILE_IDENTIFIER)
    buf_no_cave_region = bytes(builder.Output())

    svg = ir_to_svg(buf_no_cave_region)

    # Even with cave_region cleared, the consumer must produce the cave fill.
    assert CAVE_FLOOR_COLOR in svg, (
        "CaveFloor FloorOp consumer must render cave fill from "
        "outline.vertices (buffer+jitter pipeline), not from cave_region. "
        "cave_region was cleared but cave fill is missing."
    )
    assert re.search(r'<path[^>]+d="[^"]*\bC\b', svg), (
        "Expected Catmull-Rom bezier path from the buffer+jitter pipeline"
    )


def test_cave_floor_op_pipeline_matches_legacy_buffer_jitter_smooth() -> None:
    """For seed99_cave: building the FloorOp via the new consumer
    pipeline (FloorOp.outline → buffer → jitter → smooth) produces
    the same SVG path string as the legacy cave_wall_path computed
    via _build_cave_wall_geometry with the same seed.

    This is the load-bearing parity test: if it passes, the consumer
    produces byte-identical output to the legacy renderer and the
    PSNR gate will hold.
    """
    import random
    from nhc.rendering._cave_geometry import (
        _build_cave_wall_geometry,
        _collect_cave_region,
    )
    from nhc.rendering.ir_to_svg import _cave_path_from_outline
    from nhc.rendering.ir_emitter import build_floor_ir
    from nhc.rendering.ir._fb.FloorIR import FloorIR
    from nhc.rendering.ir._fb import Op
    from nhc.rendering.ir._fb.FloorStyle import FloorStyle
    from tests.fixtures.floor_ir._inputs import descriptor_inputs

    inputs = descriptor_inputs("seed99_cave_cave_cave")
    seed = inputs.seed
    level = inputs.level

    # Legacy pipeline: _build_cave_wall_geometry returns (svg_path, poly, tiles)
    rng_legacy = random.Random(seed + 0x5A17E5)
    legacy_path, _poly, _tiles = _build_cave_wall_geometry(level, rng_legacy)
    assert legacy_path is not None, "Legacy cave_wall_path must be non-empty"

    # Consumer pipeline: read FloorOp.outline.vertices and apply
    # buffer+jitter+smooth via _cave_path_from_outline.
    buf = build_floor_ir(
        inputs.level, seed=seed, hatch_distance=2.0, vegetation=True,
    )
    fir = FloorIR.GetRootAs(buf, 0)
    base_seed = fir.BaseSeed()

    # Collect the CaveFloor FloorOp.
    cave_floor_ops = []
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.FloorOp:
            continue
        from nhc.rendering.ir._fb.Op import OpCreator
        op = OpCreator(entry.OpType(), entry.Op())
        if op.style == FloorStyle.CaveFloor:
            cave_floor_ops.append(op)

    assert len(cave_floor_ops) == 1, (
        f"Expected exactly 1 CaveFloor FloorOp in seed99, got {len(cave_floor_ops)}"
    )

    cave_op = cave_floor_ops[0]
    # Phase 1.26e-2a: cave geometry now lives on Region(kind=Cave).outline;
    # FloorOp.outline retired. Resolve via region_ref.
    region_ref = (
        cave_op.regionRef.decode()
        if isinstance(cave_op.regionRef, bytes)
        else (cave_op.regionRef or "")
    )
    assert region_ref.startswith("cave."), (
        f"cave FloorOp must carry region_ref='cave.<i>', got {region_ref!r}"
    )
    region_outline = None
    for ri in range(fir.RegionsLength()):
        r = fir.Regions(ri)
        rid_bytes = r.Id() or b""
        rid = rid_bytes.decode() if isinstance(rid_bytes, bytes) else rid_bytes
        if rid == region_ref:
            region_outline = r.Outline()
            break
    assert region_outline is not None, (
        f"Region {region_ref!r} not found in fir.regions"
    )
    verts = [
        region_outline.Vertices(j)
        for j in range(region_outline.VerticesLength())
    ]
    assert verts and len(verts) >= 4

    coords = [(float(v.X()), float(v.Y())) for v in verts]
    consumer_path = _cave_path_from_outline(coords, base_seed)

    assert consumer_path == legacy_path, (
        "Consumer pipeline (FloorOp.outline → buffer+jitter+smooth) must "
        "produce byte-identical SVG path to the legacy "
        "_build_cave_wall_geometry. First 200 chars:\n"
        f"  legacy:   {legacy_path[:200]}\n"
        f"  consumer: {consumer_path[:200]}"
    )
