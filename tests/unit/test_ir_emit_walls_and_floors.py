"""Phase 1.4 — emitter populates ``FloorOp`` for rect rooms.

The emitter ships one :type:`FloorOpT` per :class:`RectShape` room
alongside the legacy :type:`WallsAndFloorsOpT.rectRooms` list. The
parallel-emission contract from plans/nhc_pure_ir_plan.md §1.4: both
lists populate identically; legacy still drives pixels (consumers do
not read FloorOp until 1.15+); the new ops land **immediately after**
the WallsAndFloorsOp entry in ``ops[]`` so the IR JSON dump stays
inspectable and 1.15's consumer switch produces correct paint order
without further rearrangement.

Wood-floor short-circuit (``ctx.interior_finish == "wood"`` with a
building polygon set) keeps suppressing legacy ``rectRooms`` and now
suppresses FloorOps the same way — the contract is "match legacy" so
1.15 doesn't accidentally reintroduce a wood-floor regression.
"""

from __future__ import annotations

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    CircleShape, Level, LShape, OctagonShape, PillShape, Rect,
    RectShape, Room, SurfaceType, TempleShape, Terrain, Tile,
)
from nhc.rendering._floor_layers import _emit_walls_and_floors_ir
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir._fb.FloorStyle import FloorStyle
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir_emitter import FloorIRBuilder, build_floor_ir

from tests.fixtures.floor_ir._inputs import descriptor_inputs


CELL = 32  # mirrors nhc.rendering._svg_helpers.CELL


def _emit_into_builder(level, *, seed: int = 0, theme: str = "dungeon"):
    """Run only ``_emit_walls_and_floors_ir`` against a level and
    return ``(builder.ops, ctx)``.

    Bypasses the full ``build_floor_ir`` pipeline so the test isolates
    the parallel-emission contract — only the WallsAndFloorsOp and the
    new FloorOp entries should land in ``ops[]``.
    """
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering.ir_emitter import (
        _build_cave_wall_geometry, _build_dungeon_polygon,
    )

    ctx = build_render_context(
        level,
        seed=seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=2.0,
        vegetation=True,
    )
    builder = FloorIRBuilder(ctx)
    _emit_walls_and_floors_ir(builder)
    return builder.ops, ctx


def _build_simple_rect_level(rects: list[Rect]) -> Level:
    """Build a small Level with the given rects as RectShape rooms.

    Tiles inside each rect are FLOOR; everything else is VOID. No
    doors, no corridor tiles — just the rect-room geometry the emitter
    needs to walk.
    """
    max_x = max(r.x2 for r in rects)
    max_y = max(r.y2 for r in rects)
    width = max_x + 2
    height = max_y + 2
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=width, height=height,
    )
    for idx, rect in enumerate(rects, start=1):
        room = Room(id=f"r{idx}", rect=rect, shape=RectShape())
        level.rooms.append(room)
        for ry in range(rect.y, rect.y2):
            for rx in range(rect.x, rect.x2):
                level.tiles[ry][rx] = Tile(terrain=Terrain.FLOOR)
    return level


def _build_smooth_shape_level(
    rooms: list[tuple[Rect, "RoomShape"]],
) -> Level:
    """Build a small Level seeded with smooth-shape rooms.

    For each ``(rect, shape)`` tuple, allocates a Room whose
    ``shape.floor_tiles(rect)`` populate as FLOOR; everything else is
    VOID. Mirrors :func:`_build_simple_rect_level` but for the
    smooth-shape variants exercised by Phase 1.5.
    """
    max_x = max(r.x2 for r, _ in rooms)
    max_y = max(r.y2 for r, _ in rooms)
    width = max_x + 2
    height = max_y + 2
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=width, height=height,
    )
    for idx, (rect, shape) in enumerate(rooms, start=1):
        room = Room(id=f"s{idx}", rect=rect, shape=shape)
        level.rooms.append(room)
        for tx, ty in shape.floor_tiles(rect):
            level.tiles[ty][tx] = Tile(terrain=Terrain.FLOOR)
    return level


# ── parallel-emission contract ────────────────────────────────


def test_floor_op_per_rect_room() -> None:
    """Every rect room produces one FloorOp.

    Each new FloorOp's outline is a 4-vertex Polygon descriptor; the
    style is :enum:`FloorStyle.DungeonFloor`.
    """
    level = _build_simple_rect_level([
        Rect(2, 2, 4, 3),
        Rect(8, 2, 5, 4),
        Rect(2, 8, 6, 5),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == 3
    for entry in floor_ops:
        outline = entry.op.outline
        assert outline is not None
        assert outline.descriptorKind == OutlineKind.Polygon
        assert outline.vertices is not None
        assert len(outline.vertices) == 4
        assert entry.op.style == FloorStyle.DungeonFloor


def test_floor_op_matches_legacy_rect_rooms() -> None:
    """FloorOp outlines align tile-for-tile with legacy ``rectRooms``.

    The emitter walks ``level.rooms`` once when populating
    ``rectRooms`` and again when emitting FloorOps; both walks must
    produce ordered lists of equal length whose entries reference the
    same room (compared by pixel-space bbox of outline vs.
    rect_room.{x,y,w,h} * CELL).
    """
    level = _build_simple_rect_level([
        Rect(1, 1, 5, 4),
        Rect(7, 2, 4, 3),
        Rect(1, 7, 4, 4),
    ])
    ops, _ = _emit_into_builder(level)

    walls_ops = [
        e for e in ops if e.opType == Op.Op.WallsAndFloorsOp
    ]
    assert len(walls_ops) == 1
    legacy_rect_rooms = walls_ops[0].op.rectRooms or []

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == len(legacy_rect_rooms)

    for floor_entry, rect_room in zip(floor_ops, legacy_rect_rooms):
        verts = floor_entry.op.outline.vertices
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        bbox_x, bbox_y = min(xs), min(ys)
        bbox_w, bbox_h = max(xs) - bbox_x, max(ys) - bbox_y
        assert bbox_x == rect_room.x * CELL
        assert bbox_y == rect_room.y * CELL
        assert bbox_w == rect_room.w * CELL
        assert bbox_h == rect_room.h * CELL


def test_floor_op_uses_dungeon_floor_style() -> None:
    """``style == FloorStyle.DungeonFloor`` for dungeon-themed levels.

    ``CaveFloor`` is reserved for the 1.6 cave emitter; rect rooms
    always carry the dungeon-floor base fill regardless of theme
    flavour (the cobblestone-family decorators paint on top later via
    DecoratorOp).
    """
    level = _build_simple_rect_level([Rect(1, 1, 4, 4)])
    for theme in ("dungeon", "crypt", "sewer"):
        ops, _ = _emit_into_builder(level, theme=theme)
        floor_ops = [
            e for e in ops if e.opType == Op.Op.FloorOp
        ]
        assert len(floor_ops) == 1, (
            f"theme={theme!r}: expected one FloorOp"
        )
        assert floor_ops[0].op.style == FloorStyle.DungeonFloor


def test_floor_op_skipped_when_suppress_rect_rooms() -> None:
    """Wood-floor + building polygon → suppress both legacy and new.

    The wood-floor short-circuit lives in ``_emit_walls_and_floors_ir``
    when ``ctx.interior_finish == "wood"`` and a building polygon is
    set; today it suppresses the legacy ``rectRooms`` list because the
    bbox would extend past the chamfered footprint and bleed white
    tiles past the wood polygon. The new FloorOps must mirror that
    suppression — no FloorOp ships when ``suppress_rect_rooms`` is
    True so 1.15's consumer switch can't accidentally reintroduce the
    wood-floor leak.
    """
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering.ir_emitter import (
        _build_cave_wall_geometry, _build_dungeon_polygon,
    )

    level = _build_simple_rect_level([
        Rect(1, 1, 4, 4),
        Rect(6, 1, 4, 4),
    ])
    # Drive the wood-floor short-circuit: build_render_context reads
    # ``level.interior_floor`` to populate ``ctx.interior_finish``.
    level.interior_floor = "wood"
    ctx = build_render_context(
        level,
        seed=0,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=2.0,
        vegetation=True,
        building_polygon=[
            (32.0, 32.0), (320.0, 32.0),
            (320.0, 160.0), (32.0, 160.0),
        ],
    )
    assert ctx.interior_finish == "wood"
    assert ctx.building_polygon is not None
    builder = FloorIRBuilder(ctx)
    _emit_walls_and_floors_ir(builder)

    walls_ops = [
        e for e in builder.ops if e.opType == Op.Op.WallsAndFloorsOp
    ]
    assert len(walls_ops) == 1
    assert not walls_ops[0].op.rectRooms, (
        "suppress_rect_rooms should clear the legacy rectRooms list"
    )
    floor_ops = [
        e for e in builder.ops if e.opType == Op.Op.FloorOp
    ]
    assert floor_ops == [], (
        "suppress_rect_rooms should suppress the new FloorOps to "
        "match the legacy short-circuit"
    )


def test_floor_op_placement_in_ops_array() -> None:
    """FloorOps land **immediately after** the WallsAndFloorsOp entry.

    Pinning the placement preserves IR JSON dump inspectability (the
    parallel emission stays grouped) and gives 1.15's consumer switch
    correct paint order without further rearrangement (FloorOp paints
    the base fill before any other layer per design/map_ir_v4.md §4).
    """
    level = _build_simple_rect_level([
        Rect(1, 1, 4, 4),
        Rect(6, 1, 4, 4),
    ])
    ops, _ = _emit_into_builder(level)

    op_types = [e.opType for e in ops]
    assert Op.Op.WallsAndFloorsOp in op_types, (
        "the legacy WallsAndFloorsOp must still ship — Phase 1.4 is "
        "parallel emission, not a switch"
    )
    waf_idx = op_types.index(Op.Op.WallsAndFloorsOp)
    n_rect_rooms = sum(
        1 for r in level.rooms if isinstance(r.shape, RectShape)
    )
    expected_floor_op_slots = list(
        range(waf_idx + 1, waf_idx + 1 + n_rect_rooms)
    )
    for slot in expected_floor_op_slots:
        assert ops[slot].opType == Op.Op.FloorOp, (
            f"slot {slot}: expected FloorOp immediately after "
            f"WallsAndFloorsOp at index {waf_idx}"
        )


# ── full-pipeline parity through build_floor_ir ────────────────


def test_floor_op_round_trips_through_build_floor_ir() -> None:
    """The new FloorOps survive the FlatBuffer pack/unpack round-trip
    via ``build_floor_ir``.

    Catches any FB binding gap between the Object-API write side and
    the byte-buffer read side (e.g. the union variant not being wired
    in :func:`OpCreator`).
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    floor_ops = [
        e for e in fir.ops if e.opType == Op.Op.FloorOp
    ]
    walls_ops = [
        e for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp
    ]
    assert len(walls_ops) == 1
    legacy_rect_rooms = walls_ops[0].op.rectRooms or []
    legacy_corridor_tiles = walls_ops[0].op.corridorTiles or []
    # Phase 1.4 covers rect rooms; Phase 1.7 adds one FloorOp per
    # corridor tile. The fixture is rect-only (no smooth / cave
    # rooms), so the FloorOp count is rect_rooms + corridor_tiles.
    expected = len(legacy_rect_rooms) + len(legacy_corridor_tiles)
    assert len(floor_ops) == expected
    assert len(floor_ops) > 0, (
        "seed42_rect_dungeon_dungeon ships >0 rect rooms — the "
        "parallel-emission contract requires the same count of "
        "FloorOps"
    )
    for entry in floor_ops:
        assert entry.op.outline is not None
        assert entry.op.outline.descriptorKind == OutlineKind.Polygon
        assert len(entry.op.outline.vertices) == 4
        assert entry.op.style == FloorStyle.DungeonFloor


# ── Phase 1.5: per-shape FloorOp emission ──────────────────────


def test_floor_op_for_octagon_room() -> None:
    """An OctagonShape room emits one FloorOp with an 8-vertex Polygon
    outline.

    Mirrors :func:`test_floor_op_per_rect_room` for octagon rooms: the
    descriptor stays Polygon (octagons walk via explicit vertices —
    no Circle/Pill descriptor) and the style is DungeonFloor.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 6), OctagonShape()),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == 1
    outline = floor_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.vertices is not None
    assert len(outline.vertices) == 8
    assert floor_ops[0].op.style == FloorStyle.DungeonFloor


def test_floor_op_for_l_shape_room() -> None:
    """An LShape room emits one FloorOp with a 6-vertex Polygon outline.
    """
    level = _build_smooth_shape_level([
        (Rect(1, 2, 6, 6), LShape(corner="nw")),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == 1
    outline = floor_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.vertices is not None
    assert len(outline.vertices) == 6
    assert floor_ops[0].op.style == FloorStyle.DungeonFloor


def test_floor_op_for_temple_room() -> None:
    """A TempleShape room emits one FloorOp with a Polygon outline.

    Vertex count depends on the arc-segment discretisation
    (``_temple_vertices``), so we only assert >0 vertices here — the
    helper-level ``test_outline_from_temple_room`` pins the exact
    coordinate sequence.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 9), TempleShape(flat_side="south")),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == 1
    outline = floor_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.vertices is not None
    assert len(outline.vertices) > 0
    assert floor_ops[0].op.style == FloorStyle.DungeonFloor


def test_floor_op_for_circle_room_uses_circle_descriptor() -> None:
    """A CircleShape room emits a FloorOp with a Circle-descriptor
    outline.

    Vertex list is empty; ``cx`` / ``cy`` is the rect bbox centre and
    ``rx == ry`` is the diameter / 2. The rasterisers reproduce the
    circle via their native primitives at consumption time.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 7, 7), CircleShape()),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == 1
    outline = floor_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Circle
    assert not outline.vertices
    assert outline.cx == 7 * CELL / 2
    assert outline.cy == 7 * CELL / 2
    assert outline.rx == outline.ry
    assert floor_ops[0].op.style == FloorStyle.DungeonFloor


def test_floor_op_for_pill_room_uses_pill_descriptor() -> None:
    """A PillShape room emits a FloorOp with a Pill-descriptor outline.

    Vertex list is empty; ``cx`` / ``cy`` / ``rx`` / ``ry`` carry the
    bounding-box centre and half-extents the rasterisers consume.
    """
    level = _build_smooth_shape_level([
        (Rect(2, 1, 9, 5), PillShape()),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == 1
    outline = floor_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Pill
    assert not outline.vertices
    assert outline.rx > 0
    assert outline.ry > 0
    assert floor_ops[0].op.style == FloorStyle.DungeonFloor


def test_floor_op_smooth_shapes_match_legacy_smooth_room_regions() -> None:
    """One FloorOp per smooth room aligned with legacy
    ``smoothRoomRegions``.

    Phase 1.5 mirrors Phase 1.4's parallel-emission shape: every smooth
    room that ships a legacy ``smooth_fill_svg`` entry gets a matching
    FloorOp. The two walks must produce equal-length lists in the same
    order so the consumer switch in 1.15 stays straightforward.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 6), OctagonShape()),
        (Rect(11, 0, 7, 7), CircleShape()),
        (Rect(0, 8, 9, 5), PillShape()),
    ])
    ops, _ = _emit_into_builder(level)

    walls_ops = [
        e for e in ops if e.opType == Op.Op.WallsAndFloorsOp
    ]
    assert len(walls_ops) == 1
    legacy_smooth_regions = walls_ops[0].op.smoothRoomRegions or []

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    # No RectShape rooms in this level → every FloorOp is from the
    # smooth-shape pass.
    assert len(floor_ops) == len(legacy_smooth_regions) == 3


def test_floor_op_skipped_for_smooth_shapes_when_suppress_rect_rooms() -> None:
    """Wood-floor + building polygon → smooth FloorOps suppressed.

    Phase 1.4 mirrors the legacy ``suppress_rect_rooms`` short-circuit
    for rect rooms; 1.5 extends it to smooth shapes for the same
    reason: the wood polygon paints the base fill, so per-room
    FloorOps would re-introduce the wood-floor leak the legacy
    short-circuit prevents (bbox bleeds past the chamfered footprint).
    """
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering.ir_emitter import (
        _build_cave_wall_geometry, _build_dungeon_polygon,
    )

    level = _build_smooth_shape_level([
        (Rect(1, 1, 6, 6), OctagonShape()),
        (Rect(8, 1, 5, 5), CircleShape()),
    ])
    level.interior_floor = "wood"
    ctx = build_render_context(
        level,
        seed=0,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=2.0,
        vegetation=True,
        building_polygon=[
            (32.0, 32.0), (480.0, 32.0),
            (480.0, 256.0), (32.0, 256.0),
        ],
    )
    assert ctx.interior_finish == "wood"
    assert ctx.building_polygon is not None
    builder = FloorIRBuilder(ctx)
    _emit_walls_and_floors_ir(builder)

    floor_ops = [
        e for e in builder.ops if e.opType == Op.Op.FloorOp
    ]
    assert floor_ops == [], (
        "suppress_rect_rooms must also suppress smooth-shape FloorOps "
        "so the wood-floor base fill stays the only base layer"
    )


def test_floor_op_round_trips_through_build_floor_ir_with_octagons() -> None:
    """Smooth-shape FloorOps survive the FB pack/unpack round-trip via
    ``build_floor_ir``.

    The seed7_octagon_crypt fixture mixes octagon + rect shapes; this
    catches any FB binding gap that lets octagon polygon vertices
    drop on the wire (e.g. the OutlineKind.Polygon descriptor branch
    not being wired in :func:`OpCreator`).
    """
    inputs = descriptor_inputs("seed7_octagon_crypt_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    floor_ops = [
        e for e in fir.ops if e.opType == Op.Op.FloorOp
    ]
    walls_ops = [
        e for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp
    ]
    assert len(walls_ops) == 1
    legacy_rect_rooms = walls_ops[0].op.rectRooms or []
    legacy_smooth_regions = walls_ops[0].op.smoothRoomRegions or []
    legacy_corridor_tiles = walls_ops[0].op.corridorTiles or []
    # Phase 1.7 adds one FloorOp per corridor tile alongside the room
    # FloorOps from 1.4 / 1.5; the seed7_octagon_crypt fixture mixes
    # rects + octagons + corridors, so the total is rect_rooms +
    # smooth_regions + corridor_tiles.
    expected = (
        len(legacy_rect_rooms)
        + len(legacy_smooth_regions)
        + len(legacy_corridor_tiles)
    )
    assert len(floor_ops) == expected
    # Sanity: there should be at least one Polygon outline beyond the
    # rect rooms — an octagon room contributes 8 vertices, a rect 4.
    polygon_outlines_with_8_plus_verts = [
        e for e in floor_ops
        if e.op.outline.descriptorKind == OutlineKind.Polygon
        and len(e.op.outline.vertices) >= 6
    ]
    assert polygon_outlines_with_8_plus_verts, (
        "seed7_octagon_crypt_dungeon mixes octagons + rects — at "
        "least one FloorOp must carry an octagon (>=6 vertex) outline"
    )


# ── Phase 1.6 — cave-region FloorOp ────────────────────────────


def _build_cave_shape_level(
    cave_tiles: set[tuple[int, int]],
) -> Level:
    """Build a small Level with a single CaveShape room covering the
    given tile set.

    Floor tiles are FLOOR; everything else is VOID. Mirrors
    :func:`_build_smooth_shape_level` but for the cave variant — the
    room's bbox is the tight bbox of *cave_tiles*.
    """
    if not cave_tiles:
        raise ValueError("cave_tiles must be non-empty")
    xs = [x for x, _ in cave_tiles]
    ys = [y for _, y in cave_tiles]
    x0, y0 = min(xs), min(ys)
    x1, y1 = max(xs) + 1, max(ys) + 1
    width = x1 + 2
    height = y1 + 2
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=width, height=height,
    )
    level.metadata.theme = "cave"
    rect = Rect(x0, y0, x1 - x0, y1 - y0)
    room = Room(id="c1", rect=rect, shape=CaveShape(tiles=set(cave_tiles)))
    level.rooms.append(room)
    for tx, ty in cave_tiles:
        level.tiles[ty][tx] = Tile(terrain=Terrain.FLOOR)
    return level


def test_floor_op_for_cave_carries_cave_floor_style() -> None:
    """Each CaveShape room produces one FloorOp with style=CaveFloor.

    Phase 1.6 mirrors Phase 1.4 / 1.5's parallel-emission shape: a
    cave room ships one FloorOp alongside the legacy
    ``WallsAndFloorsOp.caveRegion`` SVG path. Style is
    :enum:`FloorStyle.CaveFloor`, distinct from DungeonFloor — the
    value is reserved for the future renderer divergence pinned in
    plan §1.6 (consumers currently paint both styles identically).
    """
    # Compact 4x4 cave room — small enough that
    # ``_trace_cave_boundary_coords`` returns a non-degenerate ring
    # (≥ 4 corners after Shapely simplification).
    cave_tiles = {
        (x, y) for y in range(2, 6) for x in range(2, 6)
    }
    level = _build_cave_shape_level(cave_tiles)
    ops, _ = _emit_into_builder(level)

    floor_ops = [e for e in ops if e.opType == Op.Op.FloorOp]
    assert len(floor_ops) == 1, (
        f"expected one FloorOp for the single CaveShape room, "
        f"got {len(floor_ops)}"
    )
    assert floor_ops[0].op.style == FloorStyle.CaveFloor, (
        "cave-region FloorOp must carry FloorStyle.CaveFloor; "
        "DungeonFloor is reserved for non-cave rooms"
    )
    assert floor_ops[0].op.outline.descriptorKind == OutlineKind.Polygon
    assert floor_ops[0].op.outline.closed is True


def test_cave_outline_vertices_match_legacy_path_input() -> None:
    """The cave FloorOp.outline.vertices are the same coords list
    that today feeds ``_smooth_closed_path``.

    The renderer reproduces the centripetal Catmull-Rom curve from
    these vertices via :func:`_centripetal_bezier_cps` at consumption
    time (per design/map_ir_v4.md §3 risks, plan §1.6). Asserting the
    pre-smoothing vertex list — not the smoothed bezier path — pins
    the contract: rasterisers receive the trace-boundary coords
    verbatim.
    """
    from nhc.rendering._cave_geometry import _trace_cave_boundary_coords

    cave_tiles = {
        (x, y) for y in range(2, 6) for x in range(2, 6)
    }
    level = _build_cave_shape_level(cave_tiles)
    ops, _ = _emit_into_builder(level)

    floor_ops = [e for e in ops if e.opType == Op.Op.FloorOp]
    assert len(floor_ops) == 1
    cave_op = floor_ops[0].op

    expected_coords = _trace_cave_boundary_coords(
        level.rooms[0].floor_tiles()
    )
    # The outline must carry the trace-boundary coords verbatim — same
    # length, same ordering, same pixel-space float values.
    assert len(cave_op.outline.vertices) == len(expected_coords) >= 4
    for got, (ex, ey) in zip(cave_op.outline.vertices, expected_coords):
        assert (float(got.x), float(got.y)) == (float(ex), float(ey)), (
            "cave outline vertex must equal _trace_cave_boundary_coords "
            "output; the renderer rebuilds the bezier curve from these"
        )


def test_floor_op_for_cave_round_trips_through_build_floor_ir() -> None:
    """The cave FloorOp survives the FB pack/unpack via
    :func:`build_floor_ir`.

    seed99_cave_cave_cave is a pure-cave fixture (no rect / smooth
    rooms); every FloorOp must be a CaveFloor with a Polygon outline.
    Catches any FB binding gap that might drop the
    ``descriptor_kind=Polygon`` branch on the wire when the only
    populated outlines are cave rings.
    """
    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    floor_ops = [e for e in fir.ops if e.opType == Op.Op.FloorOp]
    walls_ops = [e for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp]
    assert len(walls_ops) == 1
    # The legacy caveRegion SVG path keeps shipping in parallel.
    assert walls_ops[0].op.caveRegion, (
        "Phase 1.6 ships parallel emission — legacy caveRegion must "
        "keep populating until 1.15+ flips the consumer"
    )
    # Pure-cave fixture: every FloorOp is CaveFloor.
    assert floor_ops, "seed99_cave fixture must carry at least one FloorOp"
    for entry in floor_ops:
        assert entry.op.style == FloorStyle.CaveFloor
        assert entry.op.outline.descriptorKind == OutlineKind.Polygon
        assert entry.op.outline.vertices is not None
        assert len(entry.op.outline.vertices) >= 4


# ── Phase 1.7 — corridor-tile FloorOp ──────────────────────────


def _build_corridor_level(
    corridor_tiles: list[tuple[int, int]],
) -> Level:
    """Build a Level with the given corridor tiles and no rooms.

    Each tile is FLOOR with ``surface_type == CORRIDOR``; everything
    else is VOID. Mirrors the corridor portion of
    :func:`_build_simple_rect_level` so the emitter walks corridor tiles
    in isolation (no room outlines, no smooth-room paths).
    """
    if not corridor_tiles:
        raise ValueError("corridor_tiles must be non-empty")
    xs = [x for x, _ in corridor_tiles]
    ys = [y for _, y in corridor_tiles]
    width = max(xs) + 2
    height = max(ys) + 2
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=width, height=height,
    )
    for tx, ty in corridor_tiles:
        level.tiles[ty][tx] = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.CORRIDOR,
        )
    return level


def test_floor_op_per_corridor_tile() -> None:
    """Every corridor tile produces one FloorOp.

    Phase 1.7 of plans/nhc_pure_ir_plan.md — parallel emission. Each
    corridor tile becomes a FloorOp with a 4-vertex Polygon outline
    (the tile's pixel-space bbox) and ``style ==
    FloorStyle.DungeonFloor``. No merging at this stage; the emitter
    ships one op per tile.
    """
    corridor_tiles = [(2, 2), (3, 2), (4, 2), (5, 5)]
    level = _build_corridor_level(corridor_tiles)
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == len(corridor_tiles)
    for entry in floor_ops:
        outline = entry.op.outline
        assert outline is not None
        assert outline.descriptorKind == OutlineKind.Polygon
        assert outline.vertices is not None
        assert len(outline.vertices) == 4
        assert entry.op.style == FloorStyle.DungeonFloor


def test_corridor_floor_op_outlines_align_with_tile_grid() -> None:
    """Each corridor FloorOp outline is the tile's pixel-space bbox.

    Vertex layout matches :func:`outline_from_rect`'s clockwise order
    starting at the top-left corner: the bbox is
    ``(x*CELL, y*CELL, CELL, CELL)``. Asserting the bbox per tile pins
    the corridor → FloorOp coord convention before any consumer reads
    the new ops in 1.15+.
    """
    corridor_tiles = [(3, 4), (7, 1), (0, 0)]
    level = _build_corridor_level(corridor_tiles)
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    assert len(floor_ops) == len(corridor_tiles)

    # The emitter walks corridor tiles in y-major / x-minor order
    # (lines 356-373 of _floor_layers.py); sort the expected list the
    # same way to align with the FloorOp output order.
    expected_sorted = sorted(corridor_tiles, key=lambda t: (t[1], t[0]))
    for entry, (tx, ty) in zip(floor_ops, expected_sorted):
        verts = entry.op.outline.vertices
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        assert min(xs) == tx * CELL
        assert min(ys) == ty * CELL
        assert max(xs) - min(xs) == CELL
        assert max(ys) - min(ys) == CELL


def test_corridor_floor_op_count_matches_legacy_corridor_tiles() -> None:
    """Count of corridor FloorOps == ``len(WallsAndFloorsOp.corridorTiles)``.

    The parallel-emission contract: legacy ``corridorTiles`` keeps
    populating; the new FloorOps emit one per corridor tile alongside.
    Asserting equal counts pins the symmetry that 1.15's consumer
    switch will lean on (the legacy path drops, the new path takes
    over without count drift).
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    walls_ops = [
        e for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp
    ]
    assert len(walls_ops) == 1
    legacy_corridor_tiles = walls_ops[0].op.corridorTiles or []
    assert len(legacy_corridor_tiles) > 0, (
        "seed42_rect_dungeon_dungeon ships >0 corridor tiles — the "
        "test relies on this fixture having corridors"
    )

    floor_ops = [
        e for e in fir.ops if e.opType == Op.Op.FloorOp
    ]
    legacy_rect_rooms = walls_ops[0].op.rectRooms or []
    # FloorOps now cover both rect rooms (Phase 1.4) and corridor tiles
    # (this commit). Each corridor FloorOp is a 4-vertex Polygon outline
    # with side length == CELL; rect-room outlines have a side >= 2 *
    # CELL (rooms are always ≥ 2 tiles wide). Filter on bbox side to
    # split corridor FloorOps from rect-room FloorOps without depending
    # on emit order.
    corridor_floor_ops = []
    for entry in floor_ops:
        outline = entry.op.outline
        if outline.descriptorKind != OutlineKind.Polygon:
            continue
        verts = outline.vertices
        if not verts or len(verts) != 4:
            continue
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if w == CELL and h == CELL:
            corridor_floor_ops.append(entry)

    assert len(corridor_floor_ops) == len(legacy_corridor_tiles), (
        f"corridor FloorOps ({len(corridor_floor_ops)}) must match "
        f"legacy corridorTiles count ({len(legacy_corridor_tiles)})"
    )
    # Sanity: total FloorOps >= rect_rooms + corridor_tiles (smooth /
    # cave shapes contribute the rest).
    assert len(floor_ops) >= len(legacy_rect_rooms) + len(legacy_corridor_tiles)
