"""Phase 1.22 — Region.outline parallel emission (schema 3.2).

Pins the contract of the v4e migration's first sub-phase:

* The IR schema bumps to ``minor == 2``.
* Every emitted Region carries an ``outline: Outline`` parallel to
  the legacy ``polygon: Polygon`` field.
* For polygon-kind regions (Dungeon / Cave / Room / Building / Site)
  the outline mirrors the source polygon: ``outline.vertices`` carries
  the same point list as ``polygon.paths``, and ``outline.rings``
  carries the multi-ring partitioning when (and only when) the
  polygon has more than one ring (single-ring outlines leave
  ``rings`` empty per ``design/map_ir_v4e.md`` §4).
* The Circle and Pill descriptor variants of ``Outline`` round-trip
  through FlatBuffers cleanly so the future per-shape Region
  emission for circle / pill rooms (1.23+) has a stable schema to
  ship.
* For fixtures with a multi-ring dungeon polygon (cave-wall holes
  or per-room subtractions), the ``Outline`` faithfully carries
  every ring with the matching ``is_hole`` flag.

No consumer behaviour change at 1.22 — every consumer continues
reading ``Region.polygon`` (parallel emission). 1.23 onwards starts
switching consumers to read ``region_ref`` and resolve through
``Region.outline``.
"""

from __future__ import annotations

import flatbuffers
import pytest

from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.PathRange import PathRangeT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RegionKind import RegionKind
from nhc.rendering.ir._fb.Vec2 import Vec2T

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


# ── Helpers ────────────────────────────────────────────────────


@pytest.fixture(scope="module", params=all_descriptors())
def emitted(request):
    """Build each starter-fixture level once per module."""
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(request.param)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    return inputs, buf, fir


def _vec2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _pack_floor_ir_with_region(region: RegionT) -> bytes:
    """Pack a minimal FloorIR carrying ``region`` for round-trip tests."""
    fir = FloorIRT()
    fir.major = 3
    fir.minor = 2
    fir.widthTiles = 16
    fir.heightTiles = 16
    fir.cell = 32
    fir.padding = 32
    fir.floorKind = 0
    fir.theme = "dungeon"
    fir.baseSeed = 0
    fir.regions = [region]
    fir.ops = []

    builder = flatbuffers.Builder(256)
    builder.Finish(fir.Pack(builder), b"NIR3")
    return bytes(builder.Output())


# ── Schema bump ────────────────────────────────────────────────


def test_schema_minor_at_least_2(emitted) -> None:
    """1.22: SCHEMA_MINOR is at least 2 (Region.outline added at 1.22).

    Subsequent v4e sub-phases (1.23 → 1.25) bump the minor further
    additively, so this lower-bound check stays green across the
    migration. The exact current minor is locked by the skeleton
    sentinel ``test_ir_emitter_skeleton::test_schema_major_is_three``.
    """
    _, _, fir = emitted
    assert fir.major == 3
    assert fir.minor >= 2, (
        f"expected schema minor ≥ 2 (Phase 1.22 bumped to 2), got "
        f"{fir.minor}; Region.outline is required from 1.22 onward."
    )


# ── Outline parallel population ────────────────────────────────


def test_every_region_has_an_outline(emitted) -> None:
    """1.22: every Region carries a populated outline parallel to polygon."""
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        assert region.outline is not None, (
            f"region {rid!r} is missing the new outline field. "
            "Phase 1.22 emits Region.outline parallel to "
            "Region.polygon for every region kind."
        )


def test_outline_vertices_mirror_polygon_paths(emitted) -> None:
    """Polygonal kinds: outline.vertices ≡ polygon.paths point-for-point."""
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        if region.outline.descriptorKind != OutlineKind.Polygon:
            continue
        if region.polygon is None or not region.polygon.paths:
            continue
        legacy = [(v.x, v.y) for v in region.polygon.paths]
        new = [(v.x, v.y) for v in (region.outline.vertices or [])]
        assert new == legacy, (
            f"region {rid!r}: outline.vertices ({len(new)} pts) does "
            f"not match polygon.paths ({len(legacy)} pts). The "
            "outline must mirror the polygon point-for-point."
        )


def test_outline_rings_match_polygon_rings_for_multiring(emitted) -> None:
    """Multi-ring polygons: outline.rings mirrors polygon.rings.

    Single-ring polygons leave outline.rings empty per v4e §4
    ("rings: [PathRange]; multi-ring partitioning; empty == single
    ring"). The legacy Polygon table uses a redundant 1-entry
    ``rings`` for single rings; the v4e Outline collapses that to
    the empty default.
    """
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        if region.outline.descriptorKind != OutlineKind.Polygon:
            continue
        if region.polygon is None:
            continue
        legacy_rings = list(region.polygon.rings or [])
        new_rings = list(region.outline.rings or [])
        if len(legacy_rings) <= 1:
            assert len(new_rings) == 0, (
                f"region {rid!r}: single-ring polygon should leave "
                f"outline.rings empty (v4e §4); got {len(new_rings)} "
                "ring entries."
            )
        else:
            assert len(new_rings) == len(legacy_rings), (
                f"region {rid!r}: multi-ring outline must mirror "
                f"every ring (got {len(new_rings)} new vs "
                f"{len(legacy_rings)} legacy)."
            )
            for i, (lr, nr) in enumerate(zip(legacy_rings, new_rings)):
                assert (nr.start, nr.count, nr.isHole) == (
                    lr.start, lr.count, lr.isHole,
                ), (
                    f"region {rid!r} ring {i}: outline ring "
                    f"({nr.start},{nr.count},hole={nr.isHole}) does "
                    f"not match polygon ring "
                    f"({lr.start},{lr.count},hole={lr.isHole})."
                )


def test_outline_closed_flag_is_true(emitted) -> None:
    """Region outlines are always closed (no open polylines at the region table)."""
    _, _, fir = emitted
    for region in fir.regions:
        rid = region.id.decode() if isinstance(region.id, bytes) else region.id
        assert region.outline.closed is True, (
            f"region {rid!r}: outline.closed must be True "
            "(open polylines belong on InteriorWallOp, not Region)."
        )


# ── Multi-ring Dungeon (cave-wall holes) ───────────────────────


def test_dungeon_region_outline_multi_ring_in_cave_fixture() -> None:
    """seed99_cave: Dungeon region's outline carries multi-ring partitioning.

    ``_shapely_to_polygon`` packs the dungeon polygon as a multi-
    ring shape: the exterior dungeon perimeter plus one or more
    cave-wall hole rings (or per-room cookie-cutter subtractions).
    The Outline must carry the same partitioning so future
    consumers reading ``Region.outline`` can render the multi-ring
    fill via FillRule::EvenOdd without falling back to the legacy
    polygon.paths field.
    """
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    dungeon = next(
        (r for r in fir.regions
         if (r.id.decode() if isinstance(r.id, bytes) else r.id) == "dungeon"),
        None,
    )
    assert dungeon is not None, "seed99_cave is missing the dungeon Region"
    assert dungeon.outline.descriptorKind == OutlineKind.Polygon
    assert len(dungeon.outline.rings) >= 2, (
        "dungeon region in seed99_cave must carry ≥ 2 rings on "
        f"outline (exterior + cave hole(s)); got "
        f"{len(dungeon.outline.rings)}."
    )
    # At least one ring must be flagged as a hole — the cave-wall
    # interior holes drive the EvenOdd fill discipline.
    hole_count = sum(
        1 for r in dungeon.outline.rings if r.isHole
    )
    assert hole_count >= 1, (
        "dungeon region must mark at least one ring as a hole "
        "(cave-wall holes / per-room subtractions are the source "
        "of multi-ringness for dungeon polygons)."
    )


# ── Descriptor round-trip (Circle / Pill) ──────────────────────


def test_circle_descriptor_outline_round_trips() -> None:
    """A synthetic Region with a Circle-descriptor Outline encodes + decodes."""
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Circle
    outline.closed = True
    outline.vertices = []
    outline.rings = []
    outline.cuts = []
    outline.cx = 256.0
    outline.cy = 256.0
    outline.rx = 96.0
    outline.ry = 96.0

    region = RegionT()
    region.id = "synthetic.circle"
    region.kind = RegionKind.Room
    region.polygon = None
    region.shapeTag = "circle"
    region.outline = outline

    buf = _pack_floor_ir_with_region(region)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.regions[0]
    assert decoded.outline.descriptorKind == OutlineKind.Circle
    assert decoded.outline.cx == pytest.approx(256.0)
    assert decoded.outline.cy == pytest.approx(256.0)
    assert decoded.outline.rx == pytest.approx(96.0)
    assert decoded.outline.ry == pytest.approx(96.0)
    assert (decoded.outline.vertices or []) == []


def test_pill_descriptor_outline_round_trips() -> None:
    """A synthetic Region with a Pill-descriptor Outline encodes + decodes."""
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Pill
    outline.closed = True
    outline.vertices = []
    outline.rings = []
    outline.cuts = []
    outline.cx = 320.0
    outline.cy = 192.0
    outline.rx = 128.0
    outline.ry = 64.0

    region = RegionT()
    region.id = "synthetic.pill"
    region.kind = RegionKind.Room
    region.polygon = None
    region.shapeTag = "pill"
    region.outline = outline

    buf = _pack_floor_ir_with_region(region)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.regions[0]
    assert decoded.outline.descriptorKind == OutlineKind.Pill
    assert decoded.outline.cx == pytest.approx(320.0)
    assert decoded.outline.cy == pytest.approx(192.0)
    assert decoded.outline.rx == pytest.approx(128.0)
    assert decoded.outline.ry == pytest.approx(64.0)


def test_polygon_outline_with_multiring_round_trips() -> None:
    """A synthetic multi-ring Polygon outline encodes + decodes preserving rings."""
    outline = OutlineT()
    outline.descriptorKind = OutlineKind.Polygon
    outline.closed = True
    outline.cuts = []
    outline.vertices = [
        # ring 0 — outer square
        _vec2(0.0, 0.0), _vec2(64.0, 0.0),
        _vec2(64.0, 64.0), _vec2(0.0, 64.0),
        # ring 1 — inner hole
        _vec2(16.0, 16.0), _vec2(16.0, 48.0),
        _vec2(48.0, 48.0), _vec2(48.0, 16.0),
    ]
    r0 = PathRangeT()
    r0.start, r0.count, r0.isHole = 0, 4, False
    r1 = PathRangeT()
    r1.start, r1.count, r1.isHole = 4, 4, True
    outline.rings = [r0, r1]

    region = RegionT()
    region.id = "synthetic.donut"
    region.kind = RegionKind.Dungeon
    region.polygon = None
    region.shapeTag = "polygon"
    region.outline = outline

    buf = _pack_floor_ir_with_region(region)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    decoded = fir.regions[0].outline
    assert decoded.descriptorKind == OutlineKind.Polygon
    assert len(decoded.vertices) == 8
    assert len(decoded.rings) == 2
    assert (decoded.rings[0].start, decoded.rings[0].count,
            decoded.rings[0].isHole) == (0, 4, False)
    assert (decoded.rings[1].start, decoded.rings[1].count,
            decoded.rings[1].isHole) == (4, 4, True)


# ── Phase 1.26d-1 — L / Temple / Cross / Circle / Pill rooms ───
#
# At 1.26b the emitter only registered Region(kind=Room) for
# Rect / Octagon / Cave / Hybrid rooms; the other five shapes
# returned ``None`` from ``_room_region_data`` and therefore
# emitted no Region. Phase 1.26d-1 closes that gap so every room
# kind has a Region the consumer can resolve via ``region_ref``
# (a precondition for 1.26e dropping ``FloorOp.outline`` /
# ``ExteriorWallOp.outline`` populating).
#
# Polygon-variant shapes (LShape / TempleShape / CrossShape) ship
# the legacy vertex list under ``Outline.descriptorKind = Polygon``.
# Descriptor variants (CircleShape / PillShape) ship a Circle /
# Pill descriptor on ``Region.outline`` so the rasteriser can use
# its native primitive — but ``Region.polygon`` still carries a
# polygonised approximation (the shadow handler reads
# ``region.Polygon()``, not ``region.Outline()``, and the
# polygon-shadow primitive needs vertices).


def _build_shaped_room_ir(shape, room_id: str = "shaped_test_room"):
    """Build a unit-level IR with a single shaped room.

    Mirrors the builder pattern used by
    ``test_ir_floor_op_region_ref::test_hybrid_room_emits_floor_op_with_region_ref``
    so the new shape coverage tests share the same structure as
    the 1.23b hybrid-region test.
    """
    from nhc.dungeon.model import (
        Level, Rect, Room, Terrain, Tile,
    )
    from nhc.rendering.ir_emitter import build_floor_ir

    rect = Rect(3, 3, 10, 8)
    room = Room(id=room_id, rect=rect, shape=shape)
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

    buf = build_floor_ir(
        level, seed=1, hatch_distance=2.0, vegetation=False,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    return fir, room.id


def _find_region_by_id(fir: FloorIRT, room_id: str):
    for r in fir.regions or []:
        rid = r.id.decode() if isinstance(r.id, bytes) else r.id
        if rid == room_id:
            return r
    return None


def _decode_shape_tag(region) -> str:
    tag = region.shapeTag
    return tag.decode() if isinstance(tag, bytes) else (tag or "")


def test_l_shape_room_emits_region_with_polygon_outline() -> None:
    """1.26d-1 — LShape rooms emit a Region(shape_tag='l_shape')."""
    from nhc.dungeon.model import LShape

    fir, room_id = _build_shaped_room_ir(LShape(corner="nw"))
    region = _find_region_by_id(fir, room_id)
    assert region is not None, (
        "LShape room must emit a Region; 1.26d-1 closes the gap "
        "for L / Temple / Cross / Circle / Pill rooms."
    )
    assert _decode_shape_tag(region) == "l_shape", (
        f"LShape Region.shape_tag must be 'l_shape'; got "
        f"{_decode_shape_tag(region)!r}"
    )
    assert region.outline is not None
    assert region.outline.descriptorKind == OutlineKind.Polygon
    assert len(region.outline.vertices) >= 6, (
        f"LShape outline needs ≥ 6 vertices (notch L); got "
        f"{len(region.outline.vertices)}"
    )


def test_temple_room_emits_region_with_polygon_outline() -> None:
    """1.26d-1 — TempleShape rooms emit a Region(shape_tag='temple')."""
    from nhc.dungeon.model import TempleShape

    fir, room_id = _build_shaped_room_ir(TempleShape(flat_side="south"))
    region = _find_region_by_id(fir, room_id)
    assert region is not None, (
        "TempleShape room must emit a Region (1.26d-1 closes the gap)."
    )
    assert _decode_shape_tag(region) == "temple"
    assert region.outline is not None
    assert region.outline.descriptorKind == OutlineKind.Polygon
    # Temple has ~3 arc caps tessellated at 12 segs each + flat side.
    assert len(region.outline.vertices) >= 6


def test_cross_room_emits_region_with_polygon_outline() -> None:
    """1.26d-1 — CrossShape rooms emit a Region(shape_tag='cross')."""
    from nhc.dungeon.model import CrossShape

    fir, room_id = _build_shaped_room_ir(CrossShape())
    region = _find_region_by_id(fir, room_id)
    assert region is not None, (
        "CrossShape room must emit a Region (1.26d-1 closes the gap)."
    )
    assert _decode_shape_tag(region) == "cross"
    assert region.outline is not None
    assert region.outline.descriptorKind == OutlineKind.Polygon
    assert len(region.outline.vertices) == 12, (
        f"CrossShape outline must carry the 12-vertex + polygon; got "
        f"{len(region.outline.vertices)}"
    )


def test_circle_room_emits_region_with_circle_descriptor() -> None:
    """1.26d-1 — CircleShape rooms emit Region with Circle descriptor outline."""
    from nhc.dungeon.model import CircleShape

    fir, room_id = _build_shaped_room_ir(CircleShape())
    region = _find_region_by_id(fir, room_id)
    assert region is not None, (
        "CircleShape room must emit a Region (1.26d-1 closes the gap)."
    )
    assert _decode_shape_tag(region) == "circle"
    assert region.outline is not None
    assert region.outline.descriptorKind == OutlineKind.Circle, (
        "CircleShape Region.outline must carry the Circle descriptor "
        "(rasterisers prefer the native primitive over a polygonised "
        "approximation)."
    )
    assert region.outline.cx > 0.0
    assert region.outline.cy > 0.0
    assert region.outline.rx > 0.0
    assert region.outline.ry > 0.0
    # Region.polygon is the polygonised approximation (shadow handler
    # reads ``region.Polygon()``); it must carry vertices so the
    # polygon-shadow primitive has something to draw.
    assert region.polygon is not None
    assert len(region.polygon.paths or []) >= 8


def test_pill_room_emits_region_with_pill_descriptor() -> None:
    """1.26d-1 — PillShape rooms emit Region with Pill descriptor outline."""
    from nhc.dungeon.model import PillShape

    fir, room_id = _build_shaped_room_ir(PillShape())
    region = _find_region_by_id(fir, room_id)
    assert region is not None, (
        "PillShape room must emit a Region (1.26d-1 closes the gap)."
    )
    assert _decode_shape_tag(region) == "pill"
    assert region.outline is not None
    assert region.outline.descriptorKind == OutlineKind.Pill, (
        "PillShape Region.outline must carry the Pill descriptor."
    )
    assert region.outline.cx > 0.0
    assert region.outline.cy > 0.0
    assert region.outline.rx > 0.0
    assert region.outline.ry > 0.0
    # ``Region.polygon`` carries a polygonised approximation that
    # the shadow handler consumes via ``region.Polygon()``.
    assert region.polygon is not None
    assert len(region.polygon.paths or []) >= 4


# ── Phase 1.26d-2 (scope-reduced) — merged corridor Region ─────
#
# At 1.26d-2 the emitter additively registers ONE
# ``Region(kind=Corridor, id="corridor")`` per floor when corridor
# tiles exist. The Region's outline is multi-ring with one ring
# per disjoint corridor connected component (computed via Shapely
# ``unary_union`` on the corridor tile boxes — same partitioning
# pattern :func:`_collect_cave_systems` uses for cave systems).
# All rings are exterior (``is_hole = false``) — corridors are not
# topologically annular.
#
# Scope reduction: per-tile corridor FloorOps still ship with
# ``region_ref = ""`` and the consumers continue to read each op's
# own bbox outline (preserves byte-equal pixel parity). The Region
# closes the structural "corridor system has no Region" gap from
# 1.24/1.26 §"Deferred coverage gaps" symbolically; a follow-up
# sub-phase migrates the per-tile FloorOps to a single merged
# FloorOp once the consumers (Python ir_to_svg + Rust floor_op)
# gain multi-ring outline rendering. See plan §1.26 split strategy
# / §1.26d.


def test_corridor_region_emitted_when_corridors_exist() -> None:
    """seed42 (rect dungeon w/ corridors): one ``Region(kind=Corridor)``."""
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    corridor_regions = [
        r for r in (fir.regions or [])
        if r.kind == RegionKind.Corridor
    ]
    assert len(corridor_regions) == 1, (
        f"expected exactly one Region(kind=Corridor) on seed42; "
        f"got {len(corridor_regions)}."
    )
    region = corridor_regions[0]
    rid = region.id.decode() if isinstance(region.id, bytes) else region.id
    assert rid == "corridor", (
        f"corridor Region id must be 'corridor'; got {rid!r}."
    )


def test_corridor_region_carries_multiring_outline() -> None:
    """seed42's ``Region(Corridor)`` outline carries one ring per component.

    The rings are populated when corridors split into more than one
    disjoint connected component (Shapely ``unary_union`` of the
    corridor tile boxes). Single-component corridor systems take the
    v4e single-ring shorthand: ``rings = []`` and ``vertices`` IS the
    single exterior ring.

    Either way the vertex count must exceed 4 (more than just one
    tile rect), and every populated ring must be exterior
    (``is_hole = False``).
    """
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    corridor_regions = [
        r for r in (fir.regions or [])
        if r.kind == RegionKind.Corridor
    ]
    assert corridor_regions, "no Region(kind=Corridor) on seed42"
    region = corridor_regions[0]
    assert region.outline is not None, (
        "Region(Corridor).outline must be populated"
    )
    assert region.outline.descriptorKind == OutlineKind.Polygon, (
        "Region(Corridor).outline must carry the Polygon descriptor."
    )
    verts = region.outline.vertices or []
    assert len(verts) > 4, (
        f"Region(Corridor) must carry the merged corridor-system "
        f"outline (more than a single tile rect's 4 vertices); got "
        f"{len(verts)}."
    )
    # All rings (when populated) must be exterior. Multi-component
    # corridors emit one ring per component; single-component
    # corridors take the v4e shorthand (``rings = []``).
    for ring in region.outline.rings or []:
        assert not ring.isHole, (
            "every ring of Region(Corridor).outline must be exterior; "
            f"got is_hole=True for ring(start={ring.start}, "
            f"count={ring.count})."
        )


def test_corridor_region_absent_when_no_corridor_tiles() -> None:
    """Cave-only / pure-room levels emit zero Region(kind=Corridor).

    A unit level with one rect room and no corridor tiles must not
    register a corridor Region — the emit gate fires only when
    corridors exist. Mirrors the same gate the per-tile FloorOp /
    CorridorWallOp emit guards.
    """
    from nhc.dungeon.model import (
        Level, Rect, RectShape, Room, Terrain, Tile,
    )
    from nhc.rendering.ir_emitter import build_floor_ir

    rect = Rect(2, 2, 4, 4)
    room = Room(id="r1", rect=rect, shape=RectShape())
    level = Level(
        id="d1", name="Dungeon Level 1", depth=1,
        width=10, height=10, rooms=[room],
        tiles=[
            [Tile(terrain=Terrain.VOID) for _ in range(10)]
            for _ in range(10)
        ],
    )
    for fx, fy in room.floor_tiles():
        level.tiles[fy][fx] = Tile(terrain=Terrain.FLOOR)

    buf = build_floor_ir(level, seed=1, hatch_distance=2.0, vegetation=False)
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    corridor_regions = [
        r for r in (fir.regions or [])
        if r.kind == RegionKind.Corridor
    ]
    assert not corridor_regions, (
        "pure-room level (no corridor tiles) must not register a "
        f"Region(kind=Corridor); got {len(corridor_regions)}."
    )
