"""Phase 1.23a — FloorOp.region_ref parallel emission (schema 3.3).

Pins the second sub-phase of the v4e migration: every emitted
:class:`FloorOp` carries a ``region_ref: string`` parallel to its
``outline``. Consumers (Python + Rust) prefer ``region_ref`` over
``outline`` — when ``region_ref`` is non-empty the renderer
resolves the geometry through ``Region.outline`` (shipped at 1.22)
instead of reading ``op.outline`` directly. Empty ``region_ref``
remains valid: the consumer falls back to ``op.outline`` (used by
corridor FloorOps that have no per-tile Region, and by 3.x
back-compat caches that pre-date the field).

This sub-phase keeps HybridShape's arc-bearing FILL on the legacy
``smoothFillSvg`` path; 1.23b finishes the migration by emitting a
HybridShape FloorOp + Region and stops populating
``smoothFillSvg``.

No pixel change at 1.23a — both the new region_ref path and the
old outline path resolve to identical geometry (the Region.outline
mirrors the source polygon point-for-point per 1.22's contract).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flatbuffers
import pytest

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir._fb.FloorOp import FloorOpT
from nhc.rendering.ir._fb.FloorStyle import FloorStyle
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RegionKind import RegionKind
from nhc.rendering.ir._fb.Vec2 import Vec2T

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "floor_ir"
)


# ── Helpers ────────────────────────────────────────────────────


def _vec2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _floor_ops(fir: FloorIRT) -> list[Any]:
    """Return every FloorOp in op-order."""
    return [
        e.op for e in (fir.ops or [])
        if e.opType == Op.Op.FloorOp
    ]


def _decode_id(rid: Any) -> str:
    return rid.decode() if isinstance(rid, bytes) else (rid or "")


def _region_ids(fir: FloorIRT) -> set[str]:
    return {_decode_id(r.id) for r in (fir.regions or [])}


def _build_emitted(descriptor: str) -> FloorIRT:
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(descriptor)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    return FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))


def _pack_floor_ir(regions: list[RegionT], ops: list[OpEntryT]) -> bytes:
    fir = FloorIRT()
    fir.major = 3
    fir.minor = 3
    fir.widthTiles = 16
    fir.heightTiles = 16
    fir.cell = 32
    fir.padding = 32
    fir.floorKind = 0
    fir.theme = "dungeon"
    fir.baseSeed = 0
    fir.regions = regions
    fir.ops = ops

    builder = flatbuffers.Builder(256)
    builder.Finish(fir.Pack(builder), b"NIR3")
    return bytes(builder.Output())


# ── Schema bump ────────────────────────────────────────────────


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_schema_minor_at_least_3(descriptor: str) -> None:
    """1.23a: SCHEMA_MINOR ≥ 3 (FloorOp.region_ref added at 1.23a).

    Subsequent v4e sub-phases (1.24 → 1.25) bump the minor further
    additively, so this lower-bound check stays green across the
    migration. The exact current minor is locked by the skeleton
    sentinel ``test_ir_emitter_skeleton::test_schema_major_is_three``.
    """
    fir = _build_emitted(descriptor)
    assert fir.major == 3
    assert fir.minor >= 3, (
        f"expected schema minor ≥ 3 (Phase 1.23a bumped to 3), got "
        f"{fir.minor}; FloorOp.region_ref is required from 1.23a "
        "onward."
    )


# ── Round-trip ─────────────────────────────────────────────────


def test_floor_op_region_ref_round_trips() -> None:
    """region_ref ships through the FB pipeline and decodes back."""
    op = FloorOpT()
    op.outline = OutlineT()
    op.outline.descriptorKind = OutlineKind.Polygon
    op.outline.closed = True
    op.outline.cuts = []
    op.outline.rings = []
    op.outline.vertices = [_vec2(0, 0), _vec2(32, 0), _vec2(32, 32), _vec2(0, 32)]
    op.style = FloorStyle.DungeonFloor
    op.regionRef = "room.synthetic.7"

    entry = OpEntryT()
    entry.opType = Op.Op.FloorOp
    entry.op = op

    region = RegionT()
    region.id = "room.synthetic.7"
    region.kind = RegionKind.Room
    region.shapeTag = "rect"
    region.polygon = None
    region.outline = OutlineT()
    region.outline.descriptorKind = OutlineKind.Polygon
    region.outline.closed = True
    region.outline.cuts = []
    region.outline.rings = []
    region.outline.vertices = list(op.outline.vertices)

    buf = _pack_floor_ir([region], [entry])
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.ops[0].op
    assert _decode_id(decoded.regionRef) == "room.synthetic.7"


def test_floor_op_consumer_prefers_region_ref_over_outline() -> None:
    """When region_ref resolves, the consumer reads geometry from the Region.

    Build a synthetic IR where the FloorOp's own ``outline`` is a
    deliberately-wrong tiny square (4×4) but the matching Region's
    outline is the intended 64×64 square. A consumer that reads
    ``op.outline`` would render a 4-pixel speck; a consumer that
    prefers ``region_ref`` renders the full 64×64 fill.

    Test calls ``_draw_floor_op_from_ir`` directly so it isolates
    the consumer-preference logic from the surrounding
    WallsAndFloorsOp dispatcher.
    """
    from nhc.rendering.ir_to_svg import _draw_floor_op_from_ir

    # Wrong (decoy) outline on the op itself
    bad = OutlineT()
    bad.descriptorKind = OutlineKind.Polygon
    bad.closed = True
    bad.cuts = []
    bad.rings = []
    bad.vertices = [_vec2(0, 0), _vec2(4, 0), _vec2(4, 4), _vec2(0, 4)]

    op = FloorOpT()
    op.outline = bad
    op.style = FloorStyle.DungeonFloor
    op.regionRef = "room.bigger"

    entry = OpEntryT()
    entry.opType = Op.Op.FloorOp
    entry.op = op

    # Correct outline on the Region — 64x64 square
    region_outline = OutlineT()
    region_outline.descriptorKind = OutlineKind.Polygon
    region_outline.closed = True
    region_outline.cuts = []
    region_outline.rings = []
    region_outline.vertices = [
        _vec2(0, 0), _vec2(64, 0), _vec2(64, 64), _vec2(0, 64),
    ]

    region = RegionT()
    region.id = "room.bigger"
    region.kind = RegionKind.Room
    region.shapeTag = "rect"
    region.polygon = None
    region.outline = region_outline

    buf = _pack_floor_ir([region], [entry])
    fir = FloorIR.GetRootAs(buf, 0)
    fb_entry = fir.Ops(0)
    frags = _draw_floor_op_from_ir(fb_entry, fir)
    assert len(frags) == 1
    points_str = frags[0]

    # Parse vertex coords from the rendered <polygon points="…"/>
    import re
    m = re.search(r'<polygon points="([^"]+)"', points_str)
    assert m, f"expected <polygon> output; got: {points_str!r}"
    coords: list[tuple[float, float]] = []
    for pair in m.group(1).split():
        x_s, _, y_s = pair.partition(",")
        coords.append((float(x_s), float(y_s)))
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert (width, height) == (64.0, 64.0), (
        f"expected the consumer to read the 64×64 region outline; "
        f"got bbox {width}×{height}. The FloorOp's own outline (4×4 "
        "decoy) must not have been used."
    )


# ── Fixture coverage: rect / smooth / cave / corridor ──────────


def test_rect_room_floor_ops_carry_region_ref_pointing_at_room() -> None:
    """seed42 (rect dungeon): every rect-room FloorOp has region_ref → Region."""
    fir = _build_emitted("seed42_rect_dungeon_dungeon")
    region_ids = _region_ids(fir)
    room_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Room
    }
    refs = {
        _decode_id(op.regionRef) for op in _floor_ops(fir)
        if _decode_id(op.regionRef)
    }
    # Every room region's id must appear as a FloorOp.region_ref
    # (the rooms emit one FloorOp each whose region_ref points at
    # the Room region).
    missing = room_region_ids - refs
    assert not missing, (
        f"some Room regions have no FloorOp ref: {sorted(missing)}"
    )
    # And every non-empty ref must resolve to a known region.
    unresolved = refs - region_ids
    assert not unresolved, (
        f"FloorOp.region_ref values do not resolve to a Region: "
        f"{sorted(unresolved)}"
    )


def test_smooth_room_floor_ops_carry_region_ref_pointing_at_room() -> None:
    """seed7 (octagon mix): smooth-room FloorOps ref the matching Room region."""
    fir = _build_emitted("seed7_octagon_crypt_dungeon")
    room_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Room
    }
    refs = {
        _decode_id(op.regionRef) for op in _floor_ops(fir)
        if _decode_id(op.regionRef)
    }
    missing = room_region_ids - refs
    assert not missing, (
        f"some smooth-room Region ids have no FloorOp ref: "
        f"{sorted(missing)}"
    )


def test_cave_floor_op_carries_cave_region_ref() -> None:
    """seed99_cave: cave FloorOps ref a per-system Region(kind=Cave).

    Phase 1.26b closes the 1.23a / 1.24 deferral. Each cave FloorOp
    (``style=CaveFloor``) emits with ``regionRef = "cave.<i>"`` for
    the i-th disjoint cave system. The matching Region carries an
    outline whose vertices mirror the FloorOp's outline vertex-for-
    vertex (both come from ``_cave_raw_exterior_coords(tile_group)``
    so the consumer sees identical geometry whether it dispatches
    through ``regionRef`` or falls back to ``op.outline``).
    """
    fir = _build_emitted("seed99_cave_cave_cave")
    cave_floor_ops = [
        op for op in _floor_ops(fir)
        if op.style == FloorStyle.CaveFloor
    ]
    assert cave_floor_ops, "seed99_cave has no CaveFloor FloorOp"

    cave_regions = {
        _decode_id(r.id): r for r in (fir.regions or [])
        if r.kind == RegionKind.Cave
    }
    assert cave_regions, "seed99_cave has no Region(kind=Cave)"

    for op in cave_floor_ops:
        ref = _decode_id(op.regionRef)
        assert ref.startswith("cave."), (
            f"cave FloorOp.regionRef must follow 'cave.<i>' format; "
            f"got {ref!r}"
        )
        region = cave_regions.get(ref)
        assert region is not None, (
            f"cave FloorOp.regionRef={ref!r} does not resolve to "
            f"any Region(kind=Cave); known: {sorted(cave_regions)}"
        )
        # Vertex-for-vertex match between op.outline and
        # region.outline (both derived from the same
        # _cave_raw_exterior_coords(tile_group) input).
        assert op.outline is not None
        assert region.outline is not None
        op_vs = [(v.x, v.y) for v in (op.outline.vertices or [])]
        region_vs = [(v.x, v.y) for v in (region.outline.vertices or [])]
        assert op_vs == region_vs, (
            f"FloorOp.outline must mirror Region.outline vertex-for-"
            f"vertex; len(op)={len(op_vs)} len(region)={len(region_vs)}"
        )


def test_cave_region_count_matches_cave_floor_op_count() -> None:
    """Phase 1.26b invariant: one cave Region per disjoint cave system,
    matching the per-system CaveFloor FloorOp emission.

    Mirrors the per-system invariant for ExteriorWallOp(CaveInk) too —
    every cave system emits exactly one Region, one FloorOp, one
    ExteriorWallOp.
    """
    from nhc.rendering.ir._fb import WallStyle as WallStyleMod
    fir = _build_emitted("seed99_cave_cave_cave")
    cave_regions = [
        r for r in (fir.regions or [])
        if r.kind == RegionKind.Cave
    ]
    cave_floor_ops = [
        op for op in _floor_ops(fir)
        if op.style == FloorStyle.CaveFloor
    ]
    cave_wall_ops = [
        e.op for e in (fir.ops or [])
        if e.opType == Op.Op.ExteriorWallOp
        and e.op.style == WallStyleMod.WallStyle.CaveInk
    ]
    assert len(cave_regions) == len(cave_floor_ops) == len(cave_wall_ops), (
        f"per-system cave invariant violated: "
        f"regions={len(cave_regions)} floor_ops={len(cave_floor_ops)} "
        f"wall_ops={len(cave_wall_ops)}"
    )


def test_corridor_floor_op_carries_corridor_region_ref() -> None:
    """Phase 1.26d-3 — the merged corridor FloorOp keys off ``"corridor"``.

    The per-tile corridor emission retired at 1.26d-3. A single
    ``FloorOp(DungeonFloor, region_ref="corridor")`` per floor now
    carries the multi-ring outline matching the
    ``Region(kind=Corridor, id="corridor")`` registered by
    :func:`emit_regions`. This test pins that contract: the merged
    corridor FloorOp exists, claims the corridor region, and any
    additional DungeonFloor FloorOp either ties to a Room region
    or to a building/wood-floor region — never to a 1×1 anonymous
    bbox.
    """
    fir = _build_emitted("seed42_rect_dungeon_dungeon")
    room_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Room
    }

    corridor_floor_ops = [
        op for op in _floor_ops(fir)
        if _decode_id(op.regionRef) == "corridor"
    ]
    assert len(corridor_floor_ops) == 1, (
        f"expected exactly one FloorOp with region_ref='corridor'; "
        f"got {len(corridor_floor_ops)}"
    )
    corridor_op = corridor_floor_ops[0]
    assert corridor_op.style == FloorStyle.DungeonFloor
    assert corridor_op.outline is not None
    assert corridor_op.outline.vertices, (
        "merged corridor FloorOp must carry vertices"
    )

    # No 1×1 bbox FloorOp should remain with empty region_ref.
    for op in _floor_ops(fir):
        if op.style != FloorStyle.DungeonFloor:
            continue
        if op.outline is None or not op.outline.vertices:
            continue
        if op.outline.descriptorKind != OutlineKind.Polygon:
            continue
        if op.outline.rings:
            continue  # multi-ring outline (the merged corridor op)
        if len(op.outline.vertices) != 4:
            continue
        xs = [v.x for v in op.outline.vertices]
        ys = [v.y for v in op.outline.vertices]
        if (max(xs) - min(xs), max(ys) - min(ys)) != (32.0, 32.0):
            continue
        ref = _decode_id(op.regionRef)
        if ref and ref in room_region_ids:
            continue  # 1×1 rect room — fine
        assert ref, (
            f"1×1 DungeonFloor FloorOp at "
            f"({xs[0]:.0f},{ys[0]:.0f}) with empty region_ref must "
            f"not exist after 1.26d-3"
        )


def test_hybrid_room_emits_floor_op_with_region_ref() -> None:
    """Phase 1.23b — HybridShape rooms emit a FloorOp + Region.

    Builds a unit-level Hybrid room and asserts the IR carries:
    - one Region with kind=Room and shape_tag = "hybrid".
    - one DungeonFloor FloorOp whose ``region_ref`` matches the
      room's id.
    """
    from nhc.dungeon.model import (
        CircleShape, HybridShape, Level, Rect, RectShape, Room,
        SurfaceType, Terrain, Tile,
    )
    from nhc.rendering.ir_emitter import build_floor_ir

    shape = HybridShape(CircleShape(), RectShape(), "vertical")
    rect = Rect(3, 3, 10, 8)
    room = Room(id="hybrid_test_room", rect=rect, shape=shape)
    level = Level(
        id="d1", name="Dungeon Level 1", depth=1,
        width=18, height=14, rooms=[room],
        tiles=[
            [Tile(terrain=Terrain.VOID) for _ in range(18)]
            for _ in range(14)
        ],
    )
    for fx, fy in room.floor_tiles():
        level.tiles[fy][fx] = Tile(terrain=Terrain.FLOOR)

    buf = build_floor_ir(level, seed=1, hatch_distance=2.0, vegetation=False)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    region_ids = {_decode_id(r.id): r for r in fir.regions}
    assert "hybrid_test_room" in region_ids, (
        f"HybridShape room must emit a Region; got region ids: "
        f"{sorted(region_ids)}"
    )
    region = region_ids["hybrid_test_room"]
    assert _decode_id(region.shapeTag) == "hybrid", (
        f"Hybrid Region shape_tag must be 'hybrid'; got "
        f"{_decode_id(region.shapeTag)!r}"
    )
    assert region.outline is not None and len(region.outline.vertices) >= 8, (
        "Hybrid Region outline must carry the tessellated polyline "
        f"(≥ 8 vertices); got "
        f"{len(region.outline.vertices) if region.outline else 0}"
    )

    dungeon_floor_ops = [
        op for op in _floor_ops(fir)
        if op.style == FloorStyle.DungeonFloor
    ]
    hybrid_refs = [
        op for op in dungeon_floor_ops
        if _decode_id(op.regionRef) == "hybrid_test_room"
    ]
    assert hybrid_refs, (
        "HybridShape must emit a DungeonFloor FloorOp with "
        "region_ref pointing at the Hybrid Region."
    )


def test_hybrid_room_smoothfillsvg_no_longer_carries_arc_fill() -> None:
    """Phase 1.23b — HybridShape FILL retired from smoothFillSvg.

    The pre-1.23b emitter appended a ``<path d="…A…">`` arc-fill
    string for every HybridShape room. After 1.23b that branch
    skips, and the HybridShape FILL ships through a FloorOp
    instead. Asserts that no ``smoothFillSvg`` entry contains an
    SVG ``A`` arc command for a Hybrid-only level.
    """
    from nhc.dungeon.model import (
        CircleShape, HybridShape, Level, Rect, RectShape, Room,
        Terrain, Tile,
    )
    from nhc.rendering.ir._fb import Op as OpMod
    from nhc.rendering.ir_emitter import build_floor_ir

    shape = HybridShape(CircleShape(), RectShape(), "vertical")
    rect = Rect(3, 3, 10, 8)
    room = Room(id="hybrid_test_room", rect=rect, shape=shape)
    level = Level(
        id="d1", name="Dungeon Level 1", depth=1,
        width=18, height=14, rooms=[room],
        tiles=[
            [Tile(terrain=Terrain.VOID) for _ in range(18)]
            for _ in range(14)
        ],
    )
    for fx, fy in room.floor_tiles():
        level.tiles[fy][fx] = Tile(terrain=Terrain.FLOOR)

    buf = build_floor_ir(level, seed=1, hatch_distance=2.0, vegetation=False)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    arc_fills: list[str] = []
    for entry in fir.ops or []:
        if entry.opType == OpMod.Op.WallsAndFloorsOp:
            wf = entry.op
            for fragment in (wf.smoothFillSvg or []):
                s = fragment.decode() if isinstance(fragment, bytes) else fragment
                if "A" in s:  # SVG arc command
                    arc_fills.append(s)
    assert not arc_fills, (
        "HybridShape FILL must not ride on smoothFillSvg arc-paths "
        f"after 1.23b; got: {arc_fills}"
    )


def test_building_wood_floor_op_region_ref_resolves() -> None:
    """seed7_brick_building (post-regen): WoodFloor FloorOps that carry
    a non-empty region_ref resolve to a Building Region.

    When ``ctx.building_polygon`` is None (the current path for the
    IR-emitter pipeline) the wood-floor emits per-tile FloorOps;
    those leave ``region_ref`` empty (no per-tile Region exists).
    When the polygon is known a single polygon FloorOp could carry
    ``region_ref = "building.<i>"``. Either way, any non-empty ref
    must resolve to a Building Region — the contract is "ref or
    empty, never dangling".

    Reads the committed ``floor.nir`` from disk so this test stays
    green pre-regen (current bytes have no region_ref → all empty
    → all pass) AND post-regen (refs populate → resolve check
    bites). Pure positive assertion; no failure on empty refs.
    """
    p = _FIXTURE_ROOT / "seed7_brick_building_floor0" / "floor.nir"
    if not p.exists():
        pytest.skip("seed7_brick_building_floor0 fixture missing")
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(p.read_bytes(), 0))
    wood_ops = [
        op for op in _floor_ops(fir)
        if op.style == FloorStyle.WoodFloor
    ]
    assert wood_ops, "seed7_brick_building has no WoodFloor FloorOp"
    building_region_ids = {
        _decode_id(r.id) for r in fir.regions
        if r.kind == RegionKind.Building
    }
    for op in wood_ops:
        ref = _decode_id(op.regionRef)
        if not ref:
            continue
        assert ref in building_region_ids, (
            f"WoodFloor FloorOp region_ref {ref!r} does not resolve "
            f"to a Building Region "
            f"(known: {sorted(building_region_ids)})."
        )


# ── Phase 1.26e-1 — _walkable_tiles_from_ir bypass-reader tests ─


def test_walkable_tiles_prefers_region_ref_over_op_outline() -> None:
    """_walkable_tiles_from_ir must dispatch through region_ref.

    Phase 1.26e-1: this helper rasterises FloorOp outlines to tile
    coords and feeds them into the CorridorWallOp footprint filter.
    Pre-1.26e-1 it bypassed region_ref and read ``op.outline``
    directly — that bypass had to disappear before 1.26e-2 could
    drop ``FloorOp.outline`` populating for ops with region_ref.

    Test pattern mirrors :func:`test_floor_op_consumer_prefers_
    region_ref_over_outline`: build a FloorIR where the FloorOp's
    own outline is a deliberately-wrong tile (e.g. (0,0)) but the
    matching Region's outline picks out a different tile (e.g.
    (10,10)). A bypass reader returns the wrong tile; a region_ref-
    aware reader returns the Region's tile.
    """
    from nhc.rendering.ir_to_svg import _walkable_tiles_from_ir

    CELL = 32

    # Decoy outline on the op: 1x1 tile at (0, 0)
    bad = OutlineT()
    bad.descriptorKind = OutlineKind.Polygon
    bad.closed = True
    bad.cuts = []
    bad.rings = []
    bad.vertices = [
        _vec2(0, 0), _vec2(CELL, 0),
        _vec2(CELL, CELL), _vec2(0, CELL),
    ]

    op = FloorOpT()
    op.outline = bad
    op.style = FloorStyle.DungeonFloor
    op.regionRef = "room.elsewhere"

    entry = OpEntryT()
    entry.opType = Op.Op.FloorOp
    entry.op = op

    # Correct outline on the Region: 1x1 tile at (10, 10)
    region_outline = OutlineT()
    region_outline.descriptorKind = OutlineKind.Polygon
    region_outline.closed = True
    region_outline.cuts = []
    region_outline.rings = []
    region_outline.vertices = [
        _vec2(10 * CELL, 10 * CELL),
        _vec2(11 * CELL, 10 * CELL),
        _vec2(11 * CELL, 11 * CELL),
        _vec2(10 * CELL, 11 * CELL),
    ]

    region = RegionT()
    region.id = "room.elsewhere"
    region.kind = RegionKind.Room
    region.shapeTag = "rect"
    region.polygon = None
    region.outline = region_outline

    buf = _pack_floor_ir([region], [entry])
    fir = FloorIR.GetRootAs(buf, 0)
    tiles = _walkable_tiles_from_ir(fir)
    assert tiles == {(10, 10)}, (
        f"_walkable_tiles_from_ir must read the Region's outline, "
        f"not the FloorOp's decoy outline. Got {sorted(tiles)}; "
        "expected {(10, 10)}."
    )


def test_walkable_tiles_fallback_to_op_outline_when_no_region_ref() -> None:
    """_walkable_tiles_from_ir falls back to ``op.outline`` when ``region_ref``
    is empty.

    Building wood-floor per-tile FloorOps have no Region today
    (1.20b ships per-tile WoodFloor FloorOps because the IR-emitter
    pipeline does not currently resolve the building polygon).
    Those ops carry an empty ``regionRef`` and a populated
    ``outline``; the consumer must read the op outline directly.
    """
    from nhc.rendering.ir_to_svg import _walkable_tiles_from_ir

    CELL = 32

    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Polygon
    outline.closed = True
    outline.cuts = []
    outline.rings = []
    outline.vertices = [
        _vec2(5 * CELL, 5 * CELL),
        _vec2(6 * CELL, 5 * CELL),
        _vec2(6 * CELL, 6 * CELL),
        _vec2(5 * CELL, 6 * CELL),
    ]

    op = FloorOpT()
    op.outline = outline
    op.style = FloorStyle.DungeonFloor
    op.regionRef = ""  # no region_ref → fall back to op.outline

    entry = OpEntryT()
    entry.opType = Op.Op.FloorOp
    entry.op = op

    buf = _pack_floor_ir([], [entry])
    fir = FloorIR.GetRootAs(buf, 0)
    tiles = _walkable_tiles_from_ir(fir)
    assert tiles == {(5, 5)}, (
        f"_walkable_tiles_from_ir must fall back to op.outline when "
        f"region_ref is empty. Got {sorted(tiles)}; "
        "expected {(5, 5)}."
    )
