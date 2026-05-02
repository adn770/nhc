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
from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir._fb.FloorStyle import FloorStyle
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.WallStyle import WallStyle
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


def test_floor_op_outlines_match_source_rect_rooms() -> None:
    """FloorOp outlines align tile-for-tile with the source rect rooms.

    Phase 1.19 cleared ``rectRooms`` from the legacy WallsAndFloorsOp;
    this test pins the same invariant against ``level.rooms`` directly.
    Both the emitter's room walk and the FloorOp emit must produce the
    same N rooms in the same order at pixel-equivalent bbox.
    """
    rects = [
        Rect(1, 1, 5, 4),
        Rect(7, 2, 4, 3),
        Rect(1, 7, 4, 4),
    ]
    level = _build_simple_rect_level(rects)
    ops, _ = _emit_into_builder(level)

    floor_ops = [e for e in ops if e.opType == Op.Op.FloorOp]
    assert len(floor_ops) == len(rects)

    for floor_entry, rect in zip(floor_ops, rects):
        verts = floor_entry.op.outline.vertices
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        bbox_x, bbox_y = min(xs), min(ys)
        bbox_w, bbox_h = max(xs) - bbox_x, max(ys) - bbox_y
        assert bbox_x == rect.x * CELL
        assert bbox_y == rect.y * CELL
        assert bbox_w == rect.width * CELL
        assert bbox_h == rect.height * CELL


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
    """Wood-floor + building polygon → no DungeonFloor rect FloorOps,
    WoodFloor FloorOps take their place.

    The wood-floor short-circuit lives in ``_emit_walls_and_floors_ir``
    when ``ctx.interior_finish == "wood"`` and a building polygon is
    set; it suppresses the legacy ``rectRooms`` list and the per-room
    DungeonFloor FloorOp emission because either would bleed white
    tiles past the chamfered footprint. Phase 1.20b replaces the
    suppressed white fills with WoodFloor FloorOps that paint the
    building polygon brown — so the only FloorOps emitted under this
    short-circuit carry ``style = WoodFloor``.
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
    dungeon_ops = [e for e in floor_ops if e.op.style == FloorStyle.DungeonFloor]
    wood_ops = [e for e in floor_ops if e.op.style == FloorStyle.WoodFloor]
    assert dungeon_ops == [], (
        "suppress_rect_rooms must suppress per-room DungeonFloor "
        "FloorOps to match the legacy short-circuit"
    )
    assert len(wood_ops) == 1, (
        "suppress_rect_rooms must emit exactly one WoodFloor FloorOp "
        "carrying the building polygon (Phase 1.20b)"
    )
    assert wood_ops[0].op.outline.descriptorKind == OutlineKind.Polygon


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
    # Phase 1.4 covers rect rooms; Phase 1.7 adds one FloorOp per
    # corridor tile. The fixture is rect-only (no smooth / cave
    # rooms), so the FloorOp count is len(level.rooms) + the number
    # of corridor / door tiles iterated by `_emit_walls_and_floors_ir`.
    n_rect = sum(
        1 for r in inputs.level.rooms
        if isinstance(r.shape, RectShape)
    )
    n_corridor = sum(
        1
        for y in range(inputs.level.height)
        for x in range(inputs.level.width)
        if (
            inputs.level.tiles[y][x].terrain in (
                Terrain.FLOOR, Terrain.WATER, Terrain.GRASS, Terrain.LAVA,
            )
            and (
                inputs.level.tiles[y][x].surface_type == SurfaceType.CORRIDOR
                or "door" in (inputs.level.tiles[y][x].feature or "")
            )
        )
    )
    assert len(floor_ops) == n_rect + n_corridor
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


def test_floor_op_per_smooth_shape_room() -> None:
    """One FloorOp per smooth-shape room.

    Phase 1.5 mirrors Phase 1.4's emission shape: every smooth room
    gets one FloorOp. Phase 1.19 cleared ``smoothRoomRegions``; the
    invariant is now pinned against ``level.rooms`` directly.
    """
    smooth_rooms = [
        (Rect(0, 0, 9, 6), OctagonShape()),
        (Rect(11, 0, 7, 7), CircleShape()),
        (Rect(0, 8, 9, 5), PillShape()),
    ]
    level = _build_smooth_shape_level(smooth_rooms)
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    # No RectShape rooms in this level → every FloorOp is from the
    # smooth-shape pass.
    assert len(floor_ops) == len(smooth_rooms) == 3


def test_floor_op_skipped_for_smooth_shapes_when_suppress_rect_rooms() -> None:
    """Wood-floor + building polygon → smooth DungeonFloor FloorOps
    suppressed; one WoodFloor FloorOp paints the building polygon.

    Phase 1.4 mirrors the legacy ``suppress_rect_rooms`` short-circuit
    for rect rooms; 1.5 extended it to smooth shapes for the same
    reason: a per-room DungeonFloor FloorOp would bleed white past
    the chamfered building footprint. Phase 1.20b replaces the
    suppressed white fills with one WoodFloor FloorOp covering the
    building polygon.
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
    dungeon_ops = [e for e in floor_ops if e.op.style == FloorStyle.DungeonFloor]
    wood_ops = [e for e in floor_ops if e.op.style == FloorStyle.WoodFloor]
    assert dungeon_ops == [], (
        "suppress_rect_rooms must suppress smooth-shape DungeonFloor "
        "FloorOps so the wood polygon stays the only base layer "
        "inside the building"
    )
    assert len(wood_ops) == 1, (
        "suppress_rect_rooms must emit exactly one WoodFloor FloorOp "
        "carrying the building polygon (Phase 1.20b)"
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
    # Phase 1.19 cleared the legacy WallsAndFloorsOp counters; pin
    # against the source ``level.rooms`` + corridor-tile walk instead.
    n_rooms = sum(
        1 for r in inputs.level.rooms
        if isinstance(
            r.shape,
            (RectShape, OctagonShape, LShape, TempleShape,
             CircleShape, PillShape),
        )
    )
    n_corridor = sum(
        1
        for y in range(inputs.level.height)
        for x in range(inputs.level.width)
        if (
            inputs.level.tiles[y][x].terrain in (
                Terrain.FLOOR, Terrain.WATER, Terrain.GRASS, Terrain.LAVA,
            )
            and (
                inputs.level.tiles[y][x].surface_type == SurfaceType.CORRIDOR
                or "door" in (inputs.level.tiles[y][x].feature or "")
            )
        )
    )
    expected = n_rooms + n_corridor
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
    """ONE merged FloorOp per disjoint cave system, style=CaveFloor.

    Corrigendum to Phase 1.6 (bfe2c69): the emitter now merges all
    cave tiles before tracing — matching the legacy ``cave_wall_path``
    which calls ``_trace_cave_boundary_coords(unary_union_of_all_cave_tiles)``.
    A single CaveShape room → ONE FloorOp (merged == per-room here).
    Style is :enum:`FloorStyle.CaveFloor`, distinct from DungeonFloor.
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
        f"expected one merged FloorOp for the single cave system, "
        f"got {len(floor_ops)}"
    )
    assert floor_ops[0].op.style == FloorStyle.CaveFloor, (
        "cave-region FloorOp must carry FloorStyle.CaveFloor; "
        "DungeonFloor is reserved for non-cave rooms"
    )
    assert floor_ops[0].op.outline.descriptorKind == OutlineKind.Polygon
    assert floor_ops[0].op.outline.closed is True


def test_cave_outline_vertices_match_raw_exterior_coords() -> None:
    """The cave FloorOp.outline.vertices match the raw tile-union ring.

    Phase 1.15b real-consumer follow-up: the emitter now stores
    ``_cave_raw_exterior_coords(merged_tiles)`` (the un-simplified
    Shapely unary_union exterior ring) instead of the Douglas-Peucker
    simplified output from ``_trace_cave_boundary_coords``.  This
    allows the consumer to reconstruct ``Polygon(vertices)`` exactly
    and apply the buffer+jitter pipeline to produce byte-identical
    output to ``_build_cave_wall_geometry``.
    """
    from nhc.rendering._cave_geometry import _cave_raw_exterior_coords

    cave_tiles = {
        (x, y) for y in range(2, 6) for x in range(2, 6)
    }
    level = _build_cave_shape_level(cave_tiles)
    ops, ctx = _emit_into_builder(level)

    floor_ops = [e for e in ops if e.opType == Op.Op.FloorOp]
    assert len(floor_ops) == 1
    cave_op = floor_ops[0].op

    # Use the same merged tile set the emitter uses — ctx.cave_tiles is
    # the unified set from _collect_cave_region (room tiles + corridors).
    merged_tiles: set[tuple[int, int]] = set(ctx.cave_tiles)
    expected_coords = _cave_raw_exterior_coords(merged_tiles)
    # The outline must carry the raw exterior coords verbatim — same
    # length, same ordering, same pixel-space float values.
    assert len(cave_op.outline.vertices) == len(expected_coords) >= 4
    for got, (ex, ey) in zip(cave_op.outline.vertices, expected_coords):
        assert (float(got.x), float(got.y)) == (float(ex), float(ey)), (
            "cave outline vertex must equal _cave_raw_exterior_coords "
            "output on the merged tile set; consumer runs buffer+jitter "
            "pipeline on Polygon(vertices) to reproduce cave geometry"
        )


def test_floor_op_for_cave_round_trips_through_build_floor_ir() -> None:
    """ONE merged cave FloorOp per disjoint system via build_floor_ir.

    Corrigendum to Phase 1.6 (bfe2c69): seed99_cave_cave_cave has 8
    CaveShape rooms that form ONE connected cave system. After the fix
    the emitter emits exactly 1 cave FloorOp (not 8). Catches any FB
    binding gap on the merged outline wire.
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
    # Phase 1.19 cleared caveRegion; the cave consumer now drives
    # geometry from FloorOp.outline.vertices end-to-end.
    assert not walls_ops[0].op.caveRegion, (
        "Phase 1.19: legacy caveRegion must be empty (cave geometry "
        "lives on FloorOp.outline.vertices)"
    )
    # ONE merged FloorOp — seed99 has a single connected cave system.
    assert len(floor_ops) == 1, (
        f"expected 1 merged cave FloorOp, got {len(floor_ops)}; "
        f"8 rooms but 1 connected system"
    )
    entry = floor_ops[0]
    assert entry.op.style == FloorStyle.CaveFloor
    assert entry.op.outline.descriptorKind == OutlineKind.Polygon
    assert entry.op.outline.vertices is not None
    assert len(entry.op.outline.vertices) >= 4


def test_merged_cave_outline_matches_raw_exterior_coords() -> None:
    """Merged cave FloorOp vertices == _cave_raw_exterior_coords(cave_tiles).

    Phase 1.15b real-consumer follow-up: the emitter now stores the
    un-simplified raw exterior ring from ``_cave_raw_exterior_coords``
    so the consumer can reconstruct the exact tile-union Polygon and
    apply the buffer+jitter pipeline for byte-identical cave geometry.
    Previously stored ``_trace_cave_boundary_coords`` (simplified),
    which prevented byte-identical reconstruction.
    """
    from nhc.rendering._cave_geometry import (
        _cave_raw_exterior_coords,
        _collect_cave_region,
    )

    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    floor_ops = [e for e in fir.ops if e.opType == Op.Op.FloorOp]
    assert len(floor_ops) == 1

    # Reconstruct the merged tile set the same way build_render_context
    # does: _collect_cave_region returns room floor tiles + corridors.
    merged_tiles = _collect_cave_region(inputs.level)
    expected_coords = _cave_raw_exterior_coords(merged_tiles)

    got_vertices = floor_ops[0].op.outline.vertices
    assert len(got_vertices) == len(expected_coords) >= 4, (
        f"merged cave FloorOp must have {len(expected_coords)} vertices "
        f"(from _cave_raw_exterior_coords(merged_tiles)), "
        f"got {len(got_vertices)}"
    )
    for got, (ex, ey) in zip(got_vertices, expected_coords):
        assert (float(got.x), float(got.y)) == (float(ex), float(ey)), (
            "merged cave FloorOp vertex must equal "
            "_cave_raw_exterior_coords(merged_tiles) output; "
            "consumer calls Polygon(vertices) to reconstruct the tile "
            "union and applies buffer+jitter for byte-identical geometry"
        )


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


def test_corridor_floor_op_count_matches_source_corridor_tiles() -> None:
    """Count of corridor FloorOps == count of CORRIDOR-or-door tiles.

    Phase 1.19 cleared ``corridorTiles``; pin the count against the
    same tile-walk the emitter uses (CORRIDOR surface_type or door
    feature on FLOOR / WATER / GRASS / LAVA terrain).
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    expected_corridor_tiles = sum(
        1
        for y in range(inputs.level.height)
        for x in range(inputs.level.width)
        if (
            inputs.level.tiles[y][x].terrain in (
                Terrain.FLOOR, Terrain.WATER, Terrain.GRASS, Terrain.LAVA,
            )
            and (
                inputs.level.tiles[y][x].surface_type == SurfaceType.CORRIDOR
                or "door" in (inputs.level.tiles[y][x].feature or "")
            )
        )
    )
    assert expected_corridor_tiles > 0, (
        "seed42_rect_dungeon_dungeon ships >0 corridor tiles"
    )

    floor_ops = [
        e for e in fir.ops if e.opType == Op.Op.FloorOp
    ]
    n_rect_rooms = sum(
        1 for r in inputs.level.rooms
        if isinstance(r.shape, RectShape)
    )
    # FloorOps now cover both rect rooms (Phase 1.4) and corridor tiles
    # (Phase 1.7). Each corridor FloorOp is a 4-vertex Polygon outline
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

    assert len(corridor_floor_ops) == expected_corridor_tiles, (
        f"corridor FloorOps ({len(corridor_floor_ops)}) must match "
        f"source corridor-tile count ({expected_corridor_tiles})"
    )
    # Sanity: total FloorOps >= rect_rooms + corridor_tiles.
    assert len(floor_ops) >= n_rect_rooms + expected_corridor_tiles


# ── Phase 1.8 — rect-room ExteriorWallOp ───────────────────────


def test_exterior_wall_op_per_rect_room() -> None:
    """Every rect room produces one ExteriorWallOp.

    Phase 1.8 of plans/nhc_pure_ir_plan.md — parallel emission of
    ExteriorWallOp per :class:`RectShape` room alongside the legacy
    :type:`WallsAndFloorsOpT.wallSegments` field. Each new op carries a
    closed 4-vertex Polygon outline matching the room rect, ``style ==
    WallStyle.DungeonInk``, and ``corner_style == CornerStyle.Merlon``
    (the schema default; rect rooms aren't fortified, but the field is
    required by the union variant).
    """
    level = _build_simple_rect_level([
        Rect(2, 2, 4, 3),
        Rect(8, 2, 5, 4),
        Rect(2, 8, 6, 5),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 3
    for entry in wall_ops:
        outline = entry.op.outline
        assert outline is not None
        assert outline.descriptorKind == OutlineKind.Polygon
        assert outline.vertices is not None
        assert len(outline.vertices) == 4
        assert outline.closed is True
        assert entry.op.style == WallStyle.DungeonInk
        assert entry.op.cornerStyle == CornerStyle.Merlon


def test_exterior_wall_op_outlines_match_rect_room_floor_ops() -> None:
    """Each rect room's ExteriorWallOp.outline.vertices equals its
    FloorOp.outline.vertices.

    Both ops draw the same 4-vertex closed rect polygon (the floor
    paints the fill, the wall paints the stroke around it). Pinning
    vertex equality avoids drift between the floor- and wall-emit
    helpers and locks the contract: rect-room walls and floors share
    the same outline geometry.
    """
    level = _build_simple_rect_level([
        Rect(1, 1, 5, 4),
        Rect(7, 2, 4, 3),
        Rect(1, 7, 4, 4),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [e for e in ops if e.opType == Op.Op.FloorOp]
    wall_ops = [e for e in ops if e.opType == Op.Op.ExteriorWallOp]
    # Filter floor_ops to only rect-room FloorOps (4 vertices, side >=
    # 2*CELL since rooms are at least 2 tiles wide). No corridors /
    # smooth shapes / caves in this level, so every floor op is a rect.
    assert len(wall_ops) == len(floor_ops) == 3

    for floor_entry, wall_entry in zip(floor_ops, wall_ops):
        floor_verts = [
            (v.x, v.y) for v in floor_entry.op.outline.vertices
        ]
        wall_verts = [
            (v.x, v.y) for v in wall_entry.op.outline.vertices
        ]
        assert floor_verts == wall_verts, (
            "rect-room ExteriorWallOp must share the same 4-vertex "
            "outline as the matching FloorOp"
        )


def test_exterior_wall_op_count_matches_rect_floor_op_count() -> None:
    """Count of rect ExteriorWallOps == count of rect FloorOps.

    Phase 1.4 emits one FloorOp per rect room; Phase 1.8 emits one
    ExteriorWallOp per rect room with the same suppression rules. The
    two counts must match in lockstep so 1.15+ consumer switches don't
    introduce drift.
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    rect_rooms = [
        r for r in inputs.level.rooms
        if isinstance(r.shape, RectShape)
    ]
    assert len(rect_rooms) > 0, (
        "seed42_rect_dungeon_dungeon ships >0 rect rooms — the "
        "test relies on this fixture having rect rooms"
    )

    wall_ops = [
        e for e in fir.ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == len(rect_rooms), (
        f"rect ExteriorWallOps ({len(wall_ops)}) must match rect "
        f"room count ({len(rect_rooms)})"
    )

    # Cross-check: every rect ExteriorWallOp aligns by bbox with one
    # rect-room entry (the emit walk traverses the rooms list in order).
    for wall_entry, room in zip(wall_ops, rect_rooms):
        verts = wall_entry.op.outline.vertices
        xs = [v.x for v in verts]
        ys = [v.y for v in verts]
        bbox_x, bbox_y = min(xs), min(ys)
        bbox_w, bbox_h = max(xs) - bbox_x, max(ys) - bbox_y
        assert bbox_x == room.rect.x * CELL
        assert bbox_y == room.rect.y * CELL
        assert bbox_w == room.rect.width * CELL
        assert bbox_h == room.rect.height * CELL


def test_exterior_wall_op_skipped_when_suppress_rect_rooms() -> None:
    """Wood-floor + building polygon → ExteriorWallOps suppressed.

    Mirror of :func:`test_floor_op_skipped_when_suppress_rect_rooms`
    for walls. When the wood-floor short-circuit suppresses rect
    FloorOps (because the wood polygon paints the base fill and the
    rect bbox would bleed past the chamfered footprint), the matching
    ExteriorWallOps must drop out too — the building's own walls land
    in :type:`BuildingExteriorWallOp` / :type:`BuildingInteriorWallOp`
    instead, not on the per-rect-room outlines.
    """
    from nhc.rendering._render_context import build_render_context
    from nhc.rendering.ir_emitter import (
        _build_cave_wall_geometry, _build_dungeon_polygon,
    )

    level = _build_simple_rect_level([
        Rect(1, 1, 4, 4),
        Rect(6, 1, 4, 4),
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
            (32.0, 32.0), (320.0, 32.0),
            (320.0, 160.0), (32.0, 160.0),
        ],
    )
    assert ctx.interior_finish == "wood"
    assert ctx.building_polygon is not None
    builder = FloorIRBuilder(ctx)
    _emit_walls_and_floors_ir(builder)

    wall_ops = [
        e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert wall_ops == [], (
        "suppress_rect_rooms must suppress the rect-room "
        "ExteriorWallOps to mirror the FloorOp short-circuit"
    )


def test_exterior_wall_op_cuts_empty_pending_phase_1_11() -> None:
    """Phase 1.8 ships rect ExteriorWallOps with door cuts populated
    via :func:`cuts_for_room_doors` (the helper landed in 1.3); levels
    without door tiles must produce empty cut lists.

    The plan's §1.11 makes door-resolution explicit, but the helper is
    already complete and available, so 1.8 wires it in directly. This
    guard test pins the no-door case: a rect-room level with VOID-only
    surroundings yields ExteriorWallOps with ``cuts == []``.
    """
    level = _build_simple_rect_level([
        Rect(2, 2, 4, 3),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    assert cuts == [], (
        "rect room with no adjacent door tiles must produce an "
        "ExteriorWallOp with empty cuts"
    )


def test_exterior_wall_op_door_resolves_to_cut() -> None:
    """A door tile abutting a rect room produces one Cut on its
    ExteriorWallOp at the shared tile-edge midpoints.

    The door tile lives outside the room's floor tiles but adjacent
    to one. ``cuts_for_room_doors`` walks the room perimeter and emits
    one :class:`CutT` per door, with start / end at the pixel-space
    endpoints of the shared tile edge. ``CutStyle`` is picked from the
    door feature string (``"door"`` → ``DoorWood``).
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    # Rect room (2..6, 2..5); place a "door" tile north of (3, 2) at
    # (3, 1). The door tile must exist in the level (not VOID) and
    # carry feature == "door".
    level = _build_simple_rect_level([Rect(2, 2, 4, 3)])
    level.tiles[1][3] = Tile(terrain=Terrain.FLOOR, feature="door")

    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    assert len(cuts) == 1, (
        "expected one Cut for the single door tile north of room (3,2)"
    )
    cut = cuts[0]
    assert cut.style == CutStyle.DoorWood
    # Door is north of room tile (3, 2); the shared tile edge runs
    # from (3*CELL, 2*CELL) to (4*CELL, 2*CELL) in pixel coords.
    assert (cut.start.x, cut.start.y) == (3 * CELL, 2 * CELL)
    assert (cut.end.x, cut.end.y) == (4 * CELL, 2 * CELL)


def test_exterior_wall_op_placement_after_floor_op() -> None:
    """ExteriorWallOps land **after** FloorOp emission for the same
    room (paint order: floor before walls per design/map_ir_v4.md §4).

    Rect ExteriorWallOps are emitted in their own pass after the
    FloorOp pass. Pinning the relative slot positions guards the
    paint-order contract for the 1.16+ consumer switch.
    """
    level = _build_simple_rect_level([
        Rect(1, 1, 4, 4),
        Rect(6, 1, 4, 4),
    ])
    ops, _ = _emit_into_builder(level)

    op_types = [e.opType for e in ops]
    floor_indices = [
        i for i, t in enumerate(op_types) if t == Op.Op.FloorOp
    ]
    wall_indices = [
        i for i, t in enumerate(op_types) if t == Op.Op.ExteriorWallOp
    ]
    assert floor_indices and wall_indices
    # Every ExteriorWallOp must come after every FloorOp (floor
    # paints the base, wall strokes on top).
    assert min(wall_indices) > max(floor_indices), (
        "ExteriorWallOps must land after FloorOps in ops[] for "
        "correct paint order at the 1.16+ consumer switch"
    )


def test_exterior_wall_op_round_trips_through_build_floor_ir() -> None:
    """Rect ExteriorWallOps survive the FlatBuffer pack/unpack
    round-trip via :func:`build_floor_ir`.

    Catches any FB binding gap between the Object-API write side and
    the byte-buffer read side (e.g. the ``ExteriorWallOp`` union
    variant not being wired in :func:`OpCreator`, or the
    ``corner_style`` byte field not being preserved).
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    wall_ops = [
        e for e in fir.ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) > 0, (
        "seed42_rect_dungeon_dungeon must carry at least one rect "
        "ExteriorWallOp after Phase 1.8"
    )
    for entry in wall_ops:
        assert entry.op.outline is not None
        assert entry.op.outline.descriptorKind == OutlineKind.Polygon
        assert len(entry.op.outline.vertices) == 4
        assert entry.op.style == WallStyle.DungeonInk
        assert entry.op.cornerStyle == CornerStyle.Merlon


# ── Phase 1.9 — smooth-room ExteriorWallOp ─────────────────────


def test_exterior_wall_op_per_octagon_room() -> None:
    """An OctagonShape room emits one ExteriorWallOp with an 8-vertex
    closed Polygon outline, DungeonInk style, Merlon corner_style.

    Phase 1.9 of plans/nhc_pure_ir_plan.md mirrors Phase 1.8 (rect
    ExteriorWallOp) for the smooth-shape variants. Octagon outlines
    walk via explicit vertices — the descriptor stays Polygon (no
    Circle/Pill descriptor) and the rasterisers stroke straight
    edges between successive pairs.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 6), OctagonShape()),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    outline = wall_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.vertices is not None
    assert len(outline.vertices) == 8
    assert outline.closed is True
    assert wall_ops[0].op.style == WallStyle.DungeonInk
    assert wall_ops[0].op.cornerStyle == CornerStyle.Merlon


def test_exterior_wall_op_per_l_shape_room() -> None:
    """An LShape room emits one ExteriorWallOp with a 6-vertex closed
    Polygon outline.
    """
    level = _build_smooth_shape_level([
        (Rect(1, 2, 6, 6), LShape(corner="nw")),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    outline = wall_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.vertices is not None
    assert len(outline.vertices) == 6
    assert wall_ops[0].op.style == WallStyle.DungeonInk
    assert wall_ops[0].op.cornerStyle == CornerStyle.Merlon


def test_exterior_wall_op_per_temple_room() -> None:
    """A TempleShape room emits one ExteriorWallOp with an
    arc-discretised Polygon outline.

    Vertex count depends on the arc-segment discretisation
    (``_temple_vertices``); we assert >0 vertices here. The
    Phase 1.5 floor-pass test pins the exact coordinate sequence.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 9), TempleShape(flat_side="south")),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    outline = wall_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Polygon
    assert outline.vertices is not None
    assert len(outline.vertices) > 0
    assert wall_ops[0].op.style == WallStyle.DungeonInk


def test_exterior_wall_op_per_circle_room() -> None:
    """A CircleShape room emits an ExteriorWallOp with a Circle
    descriptor outline (cx/cy/rx==ry; empty vertex list).

    The rasterisers reproduce the circle via their native primitives
    at consumption time.
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 7, 7), CircleShape()),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    outline = wall_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Circle
    assert not outline.vertices
    assert outline.cx == 7 * CELL / 2
    assert outline.cy == 7 * CELL / 2
    assert outline.rx == outline.ry
    assert wall_ops[0].op.style == WallStyle.DungeonInk
    assert wall_ops[0].op.cornerStyle == CornerStyle.Merlon


def test_exterior_wall_op_per_pill_room() -> None:
    """A PillShape room emits an ExteriorWallOp with a Pill
    descriptor outline (cx/cy/rx/ry; empty vertex list).
    """
    level = _build_smooth_shape_level([
        (Rect(2, 1, 9, 5), PillShape()),
    ])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    outline = wall_ops[0].op.outline
    assert outline is not None
    assert outline.descriptorKind == OutlineKind.Pill
    assert not outline.vertices
    assert outline.rx > 0
    assert outline.ry > 0
    assert wall_ops[0].op.style == WallStyle.DungeonInk


def test_smooth_exterior_wall_op_count_matches_smooth_floor_op_count() -> None:
    """Smooth ExteriorWallOps == smooth FloorOps (same suppression).

    Phase 1.5 emits one FloorOp per smooth room; Phase 1.9 emits one
    ExteriorWallOp per smooth room with the same suppression rules.
    The two counts must match in lockstep (both walks share
    ``suppress_rect_rooms`` and skip CrossShape / HybridShape /
    CaveShape identically).
    """
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 6), OctagonShape()),
        (Rect(11, 0, 7, 7), CircleShape()),
        (Rect(0, 8, 9, 5), PillShape()),
    ])
    ops, _ = _emit_into_builder(level)

    floor_ops = [
        e for e in ops if e.opType == Op.Op.FloorOp
    ]
    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    # No rect rooms or corridors → every FloorOp is from the smooth
    # pass, every ExteriorWallOp is from the smooth pass.
    assert len(floor_ops) == 3
    assert len(wall_ops) == 3


def test_exterior_wall_op_skipped_for_smooth_when_suppress_rect_rooms() -> None:
    """Wood-floor + building polygon → smooth ExteriorWallOps suppressed.

    Mirrors :func:`test_floor_op_skipped_for_smooth_shapes_when_suppress_rect_rooms`
    for walls. Phase 1.5 dropped smooth FloorOps under the wood-floor
    short-circuit; Phase 1.9 must drop the matching ExteriorWallOps the
    same way — the building's own walls land in
    :type:`BuildingExteriorWallOp` / :type:`BuildingInteriorWallOp`,
    not on the per-smooth-room outlines.
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

    wall_ops = [
        e for e in builder.ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert wall_ops == [], (
        "suppress_rect_rooms must also suppress smooth-shape "
        "ExteriorWallOps so the wood-floor base fill stays the only "
        "structural layer for the building's interior"
    )


def test_doorless_gap_resolves_to_cut_style_none_on_smooth_wall() -> None:
    """A smooth room with a doorless corridor opening produces an
    ExteriorWallOp with one Cut { style: None } at the gap interval.

    Mirrors the legacy ``_outline_with_gaps`` semantics: the corridor's
    two side walls intersect the smooth outline at two points
    (``hit_a`` and ``hit_b``); the gap between them becomes a Cut with
    ``style == CutStyle.None_`` (the renderer skips the stroke for that
    interval). Doorless openings are corridors that abut the room
    without a door tile in between.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    # Octagon room (0..9, 0..6) — clip = max(1, min(9, 6) // 3) = 2.
    # Place a corridor tile north of an interior floor tile of the
    # octagon; the corridor must be SurfaceType.CORRIDOR and have no
    # door feature for ``_find_doorless_openings`` to return it.
    level = _build_smooth_shape_level([
        (Rect(0, 0, 9, 6), OctagonShape()),
    ])
    # Octagon (0..9, 0..6) clip = 2 so the top-left corner is clipped.
    # tile (4, 0) is on the top edge of the octagon (between the two
    # clipped corners). Place a corridor tile north of (4, 0) at
    # (4, -1) — but that is out of bounds. Instead, use a tile inside
    # the floor set adjacent to the room border. The floor_tiles of
    # an octagon at (0,0,9,6) include (4, 0) (top middle) — ensure it
    # is a floor first by checking shape.floor_tiles.
    floor = level.rooms[0].shape.floor_tiles(level.rooms[0].rect)
    assert (4, 0) in floor, (
        "test setup error: (4, 0) must be a floor tile of the octagon"
    )
    # Make tile (4, 0) the abutting room tile (already FLOOR). Place
    # the corridor tile north of it. Since (4, 0) is at the top edge,
    # we need a corridor at (4, -1) but that's out of bounds. Instead,
    # use a wider level so the corridor lands inside bounds.

    # Rebuild with a taller level: octagon at (0, 1, 9, 6), corridor
    # tile at (4, 0) which is north of the octagon's top edge.
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=11, height=10,
    )
    rect = Rect(0, 1, 9, 6)
    room = Room(id="o1", rect=rect, shape=OctagonShape())
    level.rooms.append(room)
    for tx, ty in room.shape.floor_tiles(rect):
        level.tiles[ty][tx] = Tile(terrain=Terrain.FLOOR)
    # Doorless corridor opening: the corridor tile abuts the octagon's
    # top edge at (4, 1) (which is a floor tile of the octagon).
    assert (4, 1) in room.shape.floor_tiles(rect), (
        "test setup error: (4, 1) must be a floor tile of the octagon"
    )
    level.tiles[0][4] = Tile(
        terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
    )

    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    # The doorless opening produces exactly one Cut at the gap interval.
    assert len(cuts) == 1, (
        f"expected one Cut for the single doorless opening, "
        f"got {len(cuts)}"
    )
    cut = cuts[0]
    assert cut.style == CutStyle.None_, (
        "doorless openings must produce Cut entries with style=None "
        "(the renderer skips the stroke for that interval)"
    )
    # The corridor wall endpoints at room tile (4, 1) on the north edge
    # are wall_a=(4*CELL, 1*CELL) and wall_b=((4+1)*CELL, 1*CELL). For
    # an octagon with clip=2*CELL, the top edge runs from
    # (clip, 1*CELL) = (2*CELL, 1*CELL) to (pw - clip, 1*CELL). Both
    # corridor walls hit the straight top edge → start.y == end.y ==
    # 1 * CELL.
    assert cut.start.y == 1 * CELL
    assert cut.end.y == 1 * CELL
    assert cut.start.x == 4 * CELL
    assert cut.end.x == 5 * CELL


def test_door_tile_resolves_to_cut_on_smooth_exterior_wall() -> None:
    """A door tile abutting a smooth room produces one Cut with the
    appropriate door-flavoured CutStyle on its ExteriorWallOp.

    ``cuts_for_room_doors`` is shape-agnostic — it walks the room's
    floor tiles (regardless of shape) and resolves each adjacent door
    tile to a Cut at the shared tile-edge midpoints in pixel coords.
    Smooth rooms reuse the same helper, so door cuts ride on smooth
    ExteriorWallOps without a separate code path.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    # Octagon room at (0, 1, 9, 6); place a "door" tile at (4, 0) north
    # of the octagon's top floor tile (4, 1).
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=11, height=10,
    )
    rect = Rect(0, 1, 9, 6)
    room = Room(id="o1", rect=rect, shape=OctagonShape())
    level.rooms.append(room)
    for tx, ty in room.shape.floor_tiles(rect):
        level.tiles[ty][tx] = Tile(terrain=Terrain.FLOOR)
    level.tiles[0][4] = Tile(terrain=Terrain.FLOOR, feature="door")

    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    assert len(cuts) == 1, (
        f"expected one Cut for the single door tile north of (4, 1), "
        f"got {len(cuts)}"
    )
    cut = cuts[0]
    assert cut.style == CutStyle.DoorWood
    # Door is north of room tile (4, 1); shared edge runs from
    # (4*CELL, 1*CELL) to (5*CELL, 1*CELL).
    assert (cut.start.x, cut.start.y) == (4 * CELL, 1 * CELL)
    assert (cut.end.x, cut.end.y) == (5 * CELL, 1 * CELL)


def test_smooth_exterior_wall_op_count_in_octagon_crypt_fixture() -> None:
    """seed7_octagon_crypt_dungeon carries one ExteriorWallOp per
    smooth room alongside the per-rect-room ones from Phase 1.8.

    The fixture mixes 10 rect + 8 octagon rooms; after Phase 1.9 the
    ExteriorWallOp count is rect_rooms + smooth_rooms_with_outline ==
    10 + 8 == 18. Pinning this in a fixture-level test catches any
    drift between the smooth-shape dispatch table and the smooth
    FloorOp dispatch.
    """
    inputs = descriptor_inputs("seed7_octagon_crypt_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    n_rect = sum(
        1 for r in inputs.level.rooms
        if isinstance(r.shape, RectShape)
    )
    n_smooth = sum(
        1 for r in inputs.level.rooms
        if isinstance(
            r.shape,
            (OctagonShape, LShape, TempleShape, CircleShape, PillShape),
        )
    )
    assert n_rect == 10
    assert n_smooth == 8

    wall_ops = [
        e for e in fir.ops if e.opType == Op.Op.ExteriorWallOp
    ]
    expected = n_rect + n_smooth
    assert len(wall_ops) == expected, (
        f"expected {expected} ExteriorWallOps (10 rect + 8 smooth) in "
        f"seed7_octagon_crypt_dungeon, got {len(wall_ops)}"
    )


# ── Phase 1.10 — cave-wall ExteriorWallOp ──────────────────────


def test_exterior_wall_op_for_cave_carries_cave_ink_style() -> None:
    """ONE merged ExteriorWallOp per disjoint cave system, style=CaveInk.

    Corrigendum to Phase 1.10 (2fce120): the emitter now merges all
    cave tiles before tracing — matching the legacy ``cave_wall_path``
    semantics. A single CaveShape room → ONE ExteriorWallOp.
    style=CaveInk, corner_style=Merlon.
    """
    cave_tiles = {
        (x, y) for y in range(2, 6) for x in range(2, 6)
    }
    level = _build_cave_shape_level(cave_tiles)
    ops, _ = _emit_into_builder(level)

    wall_ops = [e for e in ops if e.opType == Op.Op.ExteriorWallOp]
    assert len(wall_ops) == 1, (
        f"expected one merged ExteriorWallOp for the single cave system, "
        f"got {len(wall_ops)}"
    )
    assert wall_ops[0].op.style == WallStyle.CaveInk, (
        "cave-wall ExteriorWallOp must carry WallStyle.CaveInk; "
        "DungeonInk is reserved for non-cave dungeon rooms"
    )
    assert wall_ops[0].op.cornerStyle == CornerStyle.Merlon, (
        "cave ExteriorWallOp must carry CornerStyle.Merlon (the schema "
        "default required by the union variant)"
    )
    assert wall_ops[0].op.outline.descriptorKind == OutlineKind.Polygon
    assert wall_ops[0].op.outline.closed is True


def test_cave_exterior_wall_outline_matches_cave_floor_outline() -> None:
    """Cave's ExteriorWallOp.outline.vertices equal its FloorOp.outline.vertices.

    Both ops ship the same trace-boundary coords verbatim — the
    rasteriser reproduces the centripetal Catmull-Rom curve from the
    same input on the floor-fill and the wall-stroke passes. Pinning
    vertex equality catches any drift between the two emit paths so
    1.15+ / 1.16+ consumers paint floor and wall on the same outline.
    """
    cave_tiles = {
        (x, y) for y in range(2, 6) for x in range(2, 6)
    }
    level = _build_cave_shape_level(cave_tiles)
    ops, _ = _emit_into_builder(level)

    floor_ops = [e for e in ops if e.opType == Op.Op.FloorOp]
    wall_ops = [e for e in ops if e.opType == Op.Op.ExteriorWallOp]
    assert len(floor_ops) == 1
    assert len(wall_ops) == 1

    floor_vertices = floor_ops[0].op.outline.vertices
    wall_vertices = wall_ops[0].op.outline.vertices
    assert len(wall_vertices) == len(floor_vertices) >= 4, (
        "cave ExteriorWallOp.outline.vertices must match the FloorOp "
        "outline length — both share trace-boundary coords"
    )
    for fw, ww in zip(floor_vertices, wall_vertices):
        assert (float(fw.x), float(fw.y)) == (float(ww.x), float(ww.y)), (
            "cave ExteriorWallOp vertex must equal the matching FloorOp "
            "vertex; both emit paths share the same coords source"
        )


def test_cave_exterior_wall_op_has_no_cuts() -> None:
    """Caves don't have door cuts at the static-IR layer.

    Per plans/nhc_pure_ir_plan.md §1.10: ``cuts: []`` for cave
    ExteriorWallOps. Caves don't carry door tiles on their boundary in
    today's emitter (cave-to-corridor transitions are handled outside
    the cave-wall outline), so the cut list stays empty by contract.
    """
    cave_tiles = {
        (x, y) for y in range(2, 6) for x in range(2, 6)
    }
    level = _build_cave_shape_level(cave_tiles)
    ops, _ = _emit_into_builder(level)

    wall_ops = [e for e in ops if e.opType == Op.Op.ExteriorWallOp]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    assert cuts == [], (
        f"cave ExteriorWallOp must have empty cuts, got {len(cuts)} cut(s)"
    )


def test_seed99_cave_carries_one_exterior_wall_op_per_cave_region() -> None:
    """seed99_cave_cave_cave: exactly 1 merged ExteriorWallOp + 1 FloorOp.

    Corrigendum to Phase 1.10 (2fce120): the fixture has 8 CaveShape
    rooms forming ONE connected cave system; the emitter must emit ONE
    merged ExteriorWallOp (not 8) and ONE merged FloorOp (not 8).
    Round-trips through ``build_floor_ir`` so FB binding gaps surface.
    """
    inputs = descriptor_inputs("seed99_cave_cave_cave")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    floor_ops = [e for e in fir.ops if e.opType == Op.Op.FloorOp]
    wall_ops = [e for e in fir.ops if e.opType == Op.Op.ExteriorWallOp]
    walls_ops = [e for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp]
    assert len(walls_ops) == 1
    # Phase 1.19 cleared caveRegion; cave geometry now lives on
    # FloorOp.outline.vertices end-to-end.
    assert not walls_ops[0].op.caveRegion, (
        "Phase 1.19: legacy caveRegion must be empty"
    )
    # ONE merged op per disjoint cave system; seed99 has 1 system.
    assert len(floor_ops) == 1, (
        f"expected 1 merged cave FloorOp, got {len(floor_ops)}"
    )
    assert len(wall_ops) == 1, (
        f"expected 1 merged cave ExteriorWallOp, got {len(wall_ops)}"
    )
    entry = wall_ops[0]
    assert entry.op.style == WallStyle.CaveInk
    assert entry.op.cornerStyle == CornerStyle.Merlon
    assert entry.op.outline.descriptorKind == OutlineKind.Polygon
    assert entry.op.outline.vertices is not None
    assert (entry.op.outline.cuts or []) == []


def test_every_door_tile_in_every_fixture_has_a_cut() -> None:
    """Cross-fixture invariant for plan §1.11: every door tile that
    abuts a room's floor produces exactly one door-flavoured Cut on
    that room's :type:`ExteriorWallOpT`.

    Door resolution itself shipped earlier — :func:`cuts_for_room_doors`
    landed in Phase 1.3 (commit ``3cea778``) and was wired into rect
    ExteriorWallOps at 1.8 (``a6301bf``) and smooth-shape
    ExteriorWallOps at 1.9 (``c18b93b``). The per-shape unit tests
    pin the rect / smooth paths in isolation; this aggregate test
    pins the contract across the fixture suite — a regression that
    drops a door type from the helper or skips a room shape would
    show up as a count mismatch here even if the per-shape tests
    still pass (e.g. if a future shape added without being routed
    through ``cuts_for_room_doors``).
    """
    DOOR_FEATURES = {
        "door", "door_open", "door_closed", "door_locked",
        "door_secret", "door_iron", "door_stone",
    }
    DOOR_CUT_STYLES = {
        # Excludes CutStyle.None_ (== 0) — those are doorless gap
        # cuts on smooth rooms (Phase 1.9), not door tiles.
        3,  # CutStyle.DoorWood
        4,  # CutStyle.DoorStone
        5,  # CutStyle.DoorIron
        6,  # CutStyle.DoorSecret
    }

    for descriptor in (
        "seed42_rect_dungeon_dungeon",
        "seed7_octagon_crypt_dungeon",
        "seed99_cave_cave_cave",
    ):
        inputs = descriptor_inputs(descriptor)
        level = inputs.level

        # Count door tiles whose neighbour is a room floor — these
        # are exactly the tiles ``cuts_for_room_doors`` resolves.
        expected = 0
        for room in level.rooms or []:
            floor = room.floor_tiles()
            for fx, fy in floor:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = fx + dx, fy + dy
                    if (nx, ny) in floor:
                        continue
                    tile = level.tile_at(nx, ny)
                    if tile and tile.feature in DOOR_FEATURES:
                        expected += 1

        buf = build_floor_ir(
            level, seed=inputs.seed,
            hatch_distance=inputs.hatch_distance,
            vegetation=inputs.vegetation,
        )
        fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

        actual = 0
        for entry in fir.ops:
            if entry.opType != Op.Op.ExteriorWallOp:
                continue
            for cut in (entry.op.outline.cuts or []):
                if cut.style in DOOR_CUT_STYLES:
                    actual += 1

        assert actual == expected, (
            f"{descriptor}: expected {expected} door-flavoured Cuts "
            f"across all ExteriorWallOps (one per room-adjacent door "
            f"tile), got {actual}"
        )


# ── Phase 1.16b-1 — CorridorWallOp emission ─────────────────────


def test_corridor_wall_op_emitted_once_per_floor() -> None:
    """Every level with corridor tiles produces exactly one
    CorridorWallOp; floors without corridors produce zero.

    Phase 1.16b-1 of plans/nhc_pure_ir_plan.md: one op per floor
    carries the full corridor tile list; the consumer derives wall
    edges from FloorOp tile-coverage at consume time.
    """
    from nhc.rendering.ir._fb.WallStyle import WallStyle

    # Level WITH corridors → expect exactly one CorridorWallOp.
    corridor_tiles = [(2, 2), (3, 2), (4, 2), (5, 5)]
    level_with = _build_corridor_level(corridor_tiles)
    ops_with, _ = _emit_into_builder(level_with)

    corridor_wall_ops_with = [
        e for e in ops_with
        if e.opType == Op.Op.CorridorWallOp
    ]
    assert len(corridor_wall_ops_with) == 1, (
        f"expected exactly 1 CorridorWallOp for a level with corridors, "
        f"got {len(corridor_wall_ops_with)}"
    )

    # Level WITHOUT corridors → expect zero CorridorWallOps.
    level_none = Level.create_empty(
        id="floor1", name="t", depth=1, width=10, height=10,
    )
    ops_none, _ = _emit_into_builder(level_none)

    corridor_wall_ops_none = [
        e for e in ops_none
        if e.opType == Op.Op.CorridorWallOp
    ]
    assert len(corridor_wall_ops_none) == 0, (
        f"expected 0 CorridorWallOps for a level with no corridors, "
        f"got {len(corridor_wall_ops_none)}"
    )


def test_corridor_wall_op_tiles_match_source_corridor_tiles() -> None:
    """CorridorWallOp.tiles == the source CORRIDOR-or-door tile set.

    Phase 1.19 cleared ``corridorTiles``; pin the new op against the
    same tile-walk the emitter uses (CORRIDOR surface_type or door
    feature on FLOOR / WATER / GRASS / LAVA terrain).
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    expected_tiles = {
        (x, y)
        for y in range(inputs.level.height)
        for x in range(inputs.level.width)
        if (
            inputs.level.tiles[y][x].terrain in (
                Terrain.FLOOR, Terrain.WATER, Terrain.GRASS, Terrain.LAVA,
            )
            and (
                inputs.level.tiles[y][x].surface_type == SurfaceType.CORRIDOR
                or "door" in (inputs.level.tiles[y][x].feature or "")
            )
        )
    }
    assert len(expected_tiles) > 0, (
        "seed42_rect_dungeon_dungeon must have >0 corridor tiles"
    )

    corridor_wall_ops = [
        e for e in fir.ops if e.opType == Op.Op.CorridorWallOp
    ]
    assert len(corridor_wall_ops) == 1
    new_tiles = {
        (t.x, t.y)
        for t in (corridor_wall_ops[0].op.tiles or [])
    }

    assert new_tiles == expected_tiles, (
        f"CorridorWallOp.tiles ({len(new_tiles)}) does not match "
        f"source corridor-tile set ({len(expected_tiles)})"
    )


def test_corridor_wall_op_style_is_dungeon_ink() -> None:
    """Style defaults to DungeonInk.

    The style field is reserved for future cave-corridor / themed
    divergence. Phase 1.16b-1 always emits DungeonInk.
    """
    corridor_tiles = [(2, 2), (3, 2)]
    level = _build_corridor_level(corridor_tiles)
    ops, _ = _emit_into_builder(level)

    corridor_wall_ops = [
        e for e in ops if e.opType == Op.Op.CorridorWallOp
    ]
    assert len(corridor_wall_ops) == 1
    assert corridor_wall_ops[0].op.style == WallStyle.DungeonInk, (
        f"expected WallStyle.DungeonInk ({WallStyle.DungeonInk}), "
        f"got {corridor_wall_ops[0].op.style}"
    )


def test_corridor_wall_op_round_trips_through_pack_unpack() -> None:
    """Build-pack-unpack via the FlatBuffers boundary preserves the
    tile list and style.

    The seed42 fixture round-trip exercises the full
    FloorIRBuilder.finish() → FlatBuffers pack → unpack path, so
    any serialisation regression shows up here.
    """
    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    buf = build_floor_ir(
        inputs.level, seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))

    corridor_wall_ops = [
        e for e in fir.ops if e.opType == Op.Op.CorridorWallOp
    ]
    assert len(corridor_wall_ops) == 1, (
        "seed42_rect_dungeon_dungeon must produce exactly 1 "
        "CorridorWallOp after pack/unpack"
    )

    op = corridor_wall_ops[0].op
    tiles = op.tiles or []
    assert len(tiles) > 0, "CorridorWallOp.tiles must be non-empty after round-trip"
    # Every tile must have valid integer coords within the level bounds.
    level = inputs.level
    for tile in tiles:
        assert 0 <= tile.x < level.width, (
            f"tile.x={tile.x} out of bounds [0, {level.width})"
        )
        assert 0 <= tile.y < level.height, (
            f"tile.y={tile.y} out of bounds [0, {level.height})"
        )
    assert op.style == WallStyle.DungeonInk, (
        f"style must survive pack/unpack as DungeonInk, got {op.style}"
    )


# ── Phase 1.16b-2 — corridor-opening cuts on rect ExteriorWallOp ──


def _build_rect_level_with_corridor(
    rect: Rect,
    corridor_tiles: list[tuple[int, int]],
) -> Level:
    """Build a level with one RectShape room and explicit corridor tiles.

    Room floor tiles are FLOOR; corridor tiles are FLOOR +
    surface_type=CORRIDOR. Everything else is VOID. Used to test
    :func:`cuts_for_room_corridor_openings` wired into the rect
    ExteriorWallOp emitter.
    """
    max_x = max(
        rect.x2,
        *(cx for cx, _ in corridor_tiles),
    )
    max_y = max(
        rect.y2,
        *(cy for _, cy in corridor_tiles),
    )
    width = max_x + 2
    height = max_y + 2
    level = Level.create_empty(
        id="floor1", name="t", depth=1, width=width, height=height,
    )
    room = Room(id="r1", rect=rect, shape=RectShape())
    level.rooms.append(room)
    for ry in range(rect.y, rect.y2):
        for rx in range(rect.x, rect.x2):
            level.tiles[ry][rx] = Tile(terrain=Terrain.FLOOR)
    for cx, cy in corridor_tiles:
        level.tiles[cy][cx] = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.CORRIDOR,
        )
    return level


def test_rect_exterior_wall_op_cuts_include_corridor_openings() -> None:
    """Rect rooms with corridor connections produce ExteriorWallOps
    with len(cuts) == corridor_openings (no doors in this level).

    Places a corridor tile adjacent to a rect room and verifies that
    the resulting ExteriorWallOp carries one corridor-opening cut with
    CutStyle.None_.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    rect = Rect(2, 2, 4, 3)
    # Corridor tile north of room tile (2, 2).
    level = _build_rect_level_with_corridor(rect, [(2, 1)])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    corridor_cuts = [c for c in cuts if c.style == CutStyle.None_]
    assert len(corridor_cuts) == 1, (
        f"expected 1 corridor-opening cut, got {len(corridor_cuts)}"
    )


def test_corridor_opening_cut_position_matches_tile_edge() -> None:
    """Each corridor-opening cut spans exactly the corridor tile's
    CELL-wide edge in pixel coordinates.

    For a corridor tile directly north of room tile (rx, ry), the cut
    must run from (rx*CELL, ry*CELL) to ((rx+1)*CELL, ry*CELL) —
    the top edge of the room tile that abuts the corridor.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    rect = Rect(3, 3, 2, 2)
    # Corridor north of room tile (3, 3) — at (3, 2).
    level = _build_rect_level_with_corridor(rect, [(3, 2)])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    corridor_cuts = [c for c in cuts if c.style == CutStyle.None_]
    assert len(corridor_cuts) == 1
    cut = corridor_cuts[0]
    # Top edge of room tile (3, 3): x in [3*CELL, 4*CELL], y = 3*CELL.
    assert (cut.start.x, cut.start.y) == (3 * CELL, 3 * CELL), (
        f"cut.start mismatch: got ({cut.start.x}, {cut.start.y})"
    )
    assert (cut.end.x, cut.end.y) == (4 * CELL, 3 * CELL), (
        f"cut.end mismatch: got ({cut.end.x}, {cut.end.y})"
    )


def test_corridor_opening_cut_style_is_none() -> None:
    """Corridor openings produce Cut { style: CutStyle.None_ }
    (bare gap, no door visual).

    Explicitly pins that corridor cuts use the zero-value None_ style
    and not any door style — so the 1.16b-3 consumer can distinguish
    corridor gaps from door openings when walking the cut list.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    rect = Rect(2, 2, 3, 3)
    # Single corridor tile south of room tile (2, 4) — at (2, 5).
    level = _build_rect_level_with_corridor(rect, [(2, 5)])
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []
    assert len(cuts) == 1
    assert cuts[0].style == CutStyle.None_, (
        f"corridor cut must use CutStyle.None_, got {cuts[0].style}"
    )


def test_door_cuts_and_corridor_cuts_coexist() -> None:
    """A rect room with both a door AND a corridor connection produces
    ExteriorWallOp.cuts containing both kinds — a door cut
    (DoorWood) and a corridor cut (None_).

    Pins the composition of cuts_for_room_doors +
    cuts_for_room_corridor_openings in the emitter.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    # Room at (2,2) 4x3; door tile north at (2,1); corridor south at (2,5).
    rect = Rect(2, 2, 4, 3)
    level = _build_rect_level_with_corridor(rect, [(2, 5)])
    # Add a door tile north of (2, 2).
    level.tiles[1][2] = Tile(terrain=Terrain.FLOOR, feature="door")
    ops, _ = _emit_into_builder(level)

    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ]
    assert len(wall_ops) == 1
    cuts = wall_ops[0].op.outline.cuts or []

    door_cuts = [c for c in cuts if c.style == CutStyle.DoorWood]
    corridor_cuts = [c for c in cuts if c.style == CutStyle.None_]
    assert len(door_cuts) == 1, (
        f"expected 1 DoorWood cut, got {len(door_cuts)}"
    )
    assert len(corridor_cuts) == 1, (
        f"expected 1 corridor cut (None_), got {len(corridor_cuts)}"
    )


def test_seed42_rect_rooms_corridor_cut_count_matches_expected() -> None:
    """End-to-end: seed42 rect ExteriorWallOps carry exactly the right
    number of corridor-opening cuts.

    Computes the expected count by walking each rect room's perimeter
    for corridor-adjacent tiles (surface_type == CORRIDOR, walkable,
    no door feature) and asserts the total CutStyle.None_ cuts on rect
    ExteriorWallOps equals that expected count.

    In seed42 all rect rooms connect to corridors via door tiles (no
    doorless rect-room/corridor adjacency exists), so the expected
    count is 0 — which means the helper runs cleanly and adds no
    spurious cuts while door cuts are still present.
    """
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    DOOR_FEATURES = {
        "door", "door_open", "door_closed", "door_locked",
        "door_secret", "door_iron", "door_stone",
    }

    inputs = descriptor_inputs("seed42_rect_dungeon_dungeon")
    level = inputs.level
    ops, _ = _emit_into_builder(level, seed=inputs.seed)

    # Count ExteriorWallOps for rect rooms only (emitted first in the
    # op sequence; smooth rooms come in the next pass).
    rect_room_count = sum(
        1 for r in level.rooms
        if isinstance(r.shape, RectShape)
    )
    wall_ops = [
        e for e in ops if e.opType == Op.Op.ExteriorWallOp
    ][:rect_room_count]

    # Count expected corridor-opening cuts for each rect room.
    total_corridor_cuts_expected = 0
    for room in level.rooms:
        if not isinstance(room.shape, RectShape):
            continue
        floor = room.floor_tiles()
        for fx, fy in floor:
            for ddx, ddy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = fx + ddx, fy + ddy
                if (nx, ny) in floor:
                    continue
                tile = level.tile_at(nx, ny)
                if (tile and tile.surface_type == SurfaceType.CORRIDOR
                        and tile.terrain == Terrain.FLOOR
                        and (tile.feature is None
                             or tile.feature not in DOOR_FEATURES)):
                    total_corridor_cuts_expected += 1

    # Count actual CutStyle.None_ cuts on the rect ExteriorWallOps.
    total_corridor_cuts_actual = sum(
        sum(1 for c in (e.op.outline.cuts or [])
            if c.style == CutStyle.None_)
        for e in wall_ops
    )
    assert total_corridor_cuts_actual == total_corridor_cuts_expected, (
        f"seed42 rect rooms: expected {total_corridor_cuts_expected} "
        f"corridor-opening cuts (CutStyle.None_) on rect ExteriorWallOps, "
        f"got {total_corridor_cuts_actual}"
    )

    # Door cuts must still be present (regression guard).
    total_door_cuts = sum(
        sum(1 for c in (e.op.outline.cuts or [])
            if c.style != CutStyle.None_)
        for e in wall_ops
    )
    assert total_door_cuts > 0, (
        "seed42 rect rooms must still have door cuts after corridor "
        "cut addition — regression guard"
    )


# ── Phase 1.19 — legacy WallsAndFloorsOp fields cleared ──────────


def _waf_op_from_fresh_ir(descriptor: str):
    """Build a fresh IR from a fixture descriptor and return the
    WallsAndFloorsOpT from the (sole) WallsAndFloorsOp entry.

    Re-emits via ``build_floor_ir`` rather than reading the committed
    ``floor.nir`` so the test catches an emitter regression even when
    the committed fixture is stale.
    """
    inputs = descriptor_inputs(descriptor)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(bytes(buf), 0))
    waf_entries = [e for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp]
    assert len(waf_entries) == 1, (
        f"{descriptor}: expected 1 WallsAndFloorsOp, got {len(waf_entries)}"
    )
    return waf_entries[0].op


# Descriptors used as drift canaries — one rect-only dungeon, one
# smooth-shape dungeon, and the cave fixture. Each must report
# every legacy field empty after Phase 1.19 with the exception of
# ``smoothFillSvg`` (still carries CrossShape / HybridShape
# smooth-room fills until Phase 1.20c migrates them).
_PHASE_1_19_EMPTY_DESCRIPTORS = (
    "seed42_rect_dungeon_dungeon",
    "seed7_octagon_crypt_dungeon",
    "seed99_cave_cave_cave",
)


def test_legacy_walls_and_floors_fields_are_empty() -> None:
    """Phase 1.19: emitter clears the six fields with new-op coverage.

    Every freshly-emitted IR has empty ``wallSegments`` /
    ``smoothWallSvg`` / ``wallExtensionsD`` / ``caveRegion`` /
    ``smoothRoomRegions`` / ``rectRooms`` / ``corridorTiles``.

    ``smoothFillSvg`` stays populated as a transitional measure: it
    carries smooth-room base fills (white) for shapes Phase 1.5 did
    not migrate (CrossShape / HybridShape) and the smoke tests in
    test_svg_shapes.py still inspect those SVG path strings. Phase
    1.20c retires the field entirely. Phase 1.20b already retired
    the building wood-floor brown rects (now a WoodFloor FloorOp),
    so the building fixture is exercised separately in
    ``test_smooth_fill_svg_no_wood_floor_for_building`` rather than
    here (its dungeon counterpart never had wood-floor entries).
    """
    for descriptor in _PHASE_1_19_EMPTY_DESCRIPTORS:
        op = _waf_op_from_fresh_ir(descriptor)
        assert not op.wallSegments, (
            f"{descriptor}: wallSegments must be empty (driven by "
            f"ExteriorWallOp + CorridorWallOp)"
        )
        assert not op.smoothWallSvg, (
            f"{descriptor}: smoothWallSvg must be empty (driven by "
            f"smooth-shape ExteriorWallOps)"
        )
        assert not op.wallExtensionsD, (
            f"{descriptor}: wallExtensionsD must be empty (derived by "
            f"the consumer from CorridorWallOp + smooth ExteriorWallOps)"
        )
        assert not op.caveRegion, (
            f"{descriptor}: caveRegion must be empty (cave geometry "
            f"derived from CaveFloor FloorOp.outline.vertices)"
        )
        assert not op.smoothRoomRegions, (
            f"{descriptor}: smoothRoomRegions must be empty (metadata "
            f"unused by any consumer)"
        )
        assert not op.rectRooms, (
            f"{descriptor}: rectRooms must be empty (driven by "
            f"DungeonFloor FloorOp)"
        )
        assert not op.corridorTiles, (
            f"{descriptor}: corridorTiles must be empty (driven by "
            f"per-tile DungeonFloor FloorOp)"
        )


# ── Phase 1.20b — building wood-floor migrates to WoodFloor FloorOp ──


def test_smooth_fill_svg_no_wood_floor_for_building() -> None:
    """Phase 1.20b: brick_building's ``smoothFillSvg`` no longer
    carries wood-floor brown rects.

    Phase 1.19 retained the brown ``<rect fill="#B58B5A">`` entries
    because no FloorOp covered the building wood-floor base. 1.20b
    migrates them to a ``FloorStyle.WoodFloor`` FloorOp. Any leftover
    ``#B58B5A`` SVG string in ``smoothFillSvg`` would mean the legacy
    path is double-emitting alongside the new FloorOp.
    """
    from tests.samples.regenerate_fixtures import (
        _BUILDING_FIXTURES, _build_building_inputs,
    )
    fx = next(
        f for f in _BUILDING_FIXTURES
        if f.descriptor == "seed7_brick_building_floor0"
    )
    site, level = _build_building_inputs(fx)
    buf = build_floor_ir(
        level, seed=fx.seed, hatch_distance=2.0, site=site,
    )
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(bytes(buf), 0))
    waf = next(e.op for e in fir.ops if e.opType == Op.Op.WallsAndFloorsOp)
    for entry in (waf.smoothFillSvg or []):
        s = entry.decode() if isinstance(entry, bytes) else entry
        assert '#B58B5A' not in s, (
            f"smoothFillSvg must not retain wood-floor brown rects after "
            f"Phase 1.20b — found: {s[:120]}"
        )


def _building_fir() -> "FloorIRT":
    """Re-emit the brick_building fixture and return the parsed FloorIRT."""
    from tests.samples.regenerate_fixtures import (
        _BUILDING_FIXTURES, _build_building_inputs,
    )
    fx = next(
        f for f in _BUILDING_FIXTURES
        if f.descriptor == "seed7_brick_building_floor0"
    )
    site, level = _build_building_inputs(fx)
    buf = build_floor_ir(
        level, seed=fx.seed, hatch_distance=2.0, site=site,
    )
    return FloorIRT.InitFromObj(FloorIR.GetRootAs(bytes(buf), 0))


def test_building_emits_wood_floor_floor_ops() -> None:
    """Phase 1.20b: brick_building IR carries WoodFloor FloorOps,
    replacing the legacy ``smoothFillSvg`` brown-rect path.

    seed7 takes the per-tile branch (``ctx.building_polygon`` is
    None for the IR-emitter pipeline — same as legacy emit, which
    appended one ``<rect>`` per FLOOR tile). The migrated FloorOps
    mirror that 1:1: one ``style=WoodFloor`` FloorOp per building
    FLOOR tile not in ``cave_tiles``. Closes the building parity
    xfail. A future commit may compact the per-tile emission into
    a single polygon FloorOp once site → polygon resolution lands
    in the IR-emitter path.
    """
    fir = _building_fir()
    floor_ops = [e for e in fir.ops if e.opType == Op.Op.FloorOp]
    wood_ops = [
        e for e in floor_ops if e.op.style == FloorStyle.WoodFloor
    ]
    assert wood_ops, (
        "brick_building: expected at least one WoodFloor FloorOp"
    )
    for entry in wood_ops:
        wf = entry.op
        assert wf.outline is not None
        assert wf.outline.descriptorKind == OutlineKind.Polygon
        assert wf.outline.vertices is not None
        assert len(wf.outline.vertices) == 4


def test_wood_floor_ops_paint_after_dungeon_floor_ops() -> None:
    """WoodFloor FloorOps paint AFTER every white DungeonFloor /
    CaveFloor FloorOp.

    Op order is the paint order: the brown wood stamps must follow
    the white floor stamps so they cover the building interior on
    the final composite. The xfail this commit closes existed
    because the legacy ``smoothFillSvg`` field painted in
    ``WallsAndFloorsOp``'s slot — BEFORE the FloorOps — and the
    Rust gate then suppressed the legacy pass entirely. Emitting
    wood as FloorOps positioned after the white ones fixes both
    halves.
    """
    fir = _building_fir()
    floor_ops_indexed = [
        (i, e) for i, e in enumerate(fir.ops) if e.opType == Op.Op.FloorOp
    ]
    wood_indices = [
        i for i, e in floor_ops_indexed
        if e.op.style == FloorStyle.WoodFloor
    ]
    other_indices = [
        i for i, e in floor_ops_indexed
        if e.op.style != FloorStyle.WoodFloor
    ]
    assert wood_indices, "no WoodFloor FloorOp found"
    assert other_indices, (
        "expected at least one DungeonFloor FloorOp before the "
        "WoodFloor stamps (corridor or room fill)"
    )
    assert min(wood_indices) > max(other_indices), (
        f"WoodFloor FloorOps must come AFTER every DungeonFloor / "
        f"CaveFloor FloorOp; got wood min at {min(wood_indices)}, "
        f"others max at {max(other_indices)}"
    )


def test_wood_floor_per_tile_count_matches_floor_terrain() -> None:
    """Per-tile WoodFloor FloorOp count equals the number of
    FLOOR-terrain tiles outside any cave region.

    Mirrors the legacy ``smoothFillSvg`` per-tile rect emit, which
    looped over every tile and emitted one ``<rect>`` for each
    Terrain.FLOOR tile not in ``cave_tiles``. The new emit must
    produce the same 1:1 coverage so the rendered building floor
    is brown wherever the legacy output was brown.
    """
    from nhc.dungeon.model import Terrain
    from tests.samples.regenerate_fixtures import (
        _BUILDING_FIXTURES, _build_building_inputs,
    )
    fx = next(
        f for f in _BUILDING_FIXTURES
        if f.descriptor == "seed7_brick_building_floor0"
    )
    _, level = _build_building_inputs(fx)
    expected_tiles = sum(
        1
        for y in range(level.height)
        for x in range(level.width)
        if level.tiles[y][x].terrain is Terrain.FLOOR
    )
    fir = _building_fir()
    wood_ops = [
        e for e in fir.ops
        if e.opType == Op.Op.FloorOp
        and e.op.style == FloorStyle.WoodFloor
    ]
    assert len(wood_ops) == expected_tiles, (
        f"WoodFloor FloorOp count must match FLOOR-terrain tile "
        f"count; got {len(wood_ops)} ops, expected {expected_tiles}"
    )


def test_back_compat_render_for_pre_119_cache() -> None:
    """A synthetic 3.x-style IR (only legacy fields, no new ops) still
    renders pixels through the back-compat reader in
    ``walls_and_floors.rs``.

    This pins the contract that Phase 1.19's emitter change does not
    break players' existing autosaves — the gates in
    ``transform_walls_and_floors`` only suppress legacy passes when
    the corresponding new op is present. With no FloorOp /
    ExteriorWallOp / CorridorWallOp in the IR, every legacy pass
    runs. The output must contain non-background pixels.
    """
    import nhc_render
    from flatbuffers import Builder
    from nhc.rendering.ir._fb.FloorIR import (
        FloorIR as _FloorIR,
        FloorIRStart, FloorIRAddMajor, FloorIRAddMinor,
        FloorIRAddWidthTiles, FloorIRAddHeightTiles,
        FloorIRAddCell, FloorIRAddPadding, FloorIRAddTheme,
        FloorIRAddOps, FloorIRAddBaseSeed, FloorIREnd,
        FloorIRStartOpsVector,
    )
    from nhc.rendering.ir._fb.WallsAndFloorsOp import (
        WallsAndFloorsOpStart, WallsAndFloorsOpAddRectRooms,
        WallsAndFloorsOpEnd, WallsAndFloorsOpStartRectRoomsVector,
    )
    from nhc.rendering.ir._fb.RectRoom import (
        RectRoomStart, RectRoomAddX, RectRoomAddY,
        RectRoomAddW, RectRoomAddH, RectRoomEnd,
    )
    from nhc.rendering.ir._fb.OpEntry import (
        OpEntryStart, OpEntryAddOpType, OpEntryAddOp, OpEntryEnd,
    )

    # Build a 3.x-style IR with one RectRoom and nothing else — the
    # legacy ``draw_rect_rooms`` pass should paint a white rect.
    b = Builder(1024)
    theme = b.CreateString("dungeon")

    RectRoomStart(b)
    RectRoomAddX(b, 1)
    RectRoomAddY(b, 1)
    RectRoomAddW(b, 4)
    RectRoomAddH(b, 4)
    rect = RectRoomEnd(b)

    WallsAndFloorsOpStartRectRoomsVector(b, 1)
    b.PrependUOffsetTRelative(rect)
    rect_rooms_vec = b.EndVector()

    WallsAndFloorsOpStart(b)
    WallsAndFloorsOpAddRectRooms(b, rect_rooms_vec)
    waf = WallsAndFloorsOpEnd(b)

    OpEntryStart(b)
    OpEntryAddOpType(b, Op.Op.WallsAndFloorsOp)
    OpEntryAddOp(b, waf)
    entry = OpEntryEnd(b)

    FloorIRStartOpsVector(b, 1)
    b.PrependUOffsetTRelative(entry)
    ops_vec = b.EndVector()

    FloorIRStart(b)
    FloorIRAddMajor(b, 3)
    FloorIRAddMinor(b, 1)
    FloorIRAddWidthTiles(b, 6)
    FloorIRAddHeightTiles(b, 6)
    FloorIRAddCell(b, 32)
    FloorIRAddPadding(b, 32)
    FloorIRAddTheme(b, theme)
    FloorIRAddOps(b, ops_vec)
    FloorIRAddBaseSeed(b, 0)
    fir = FloorIREnd(b)
    b.Finish(fir, file_identifier=b"NIR3")
    buf = bytes(b.Output())

    png = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    assert len(png) > 100, "PNG output too small — handler crashed?"
    # Decode and assert non-background pixels exist (the legacy
    # draw_rect_rooms pass painted FLOOR_COLOR=white inside the rect).
    import io
    import numpy as np
    from PIL import Image
    arr = np.asarray(
        Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.uint8
    )
    bg = np.array([0xF5, 0xED, 0xE0], dtype=np.uint8)
    non_bg = int(np.any(arr != bg, axis=-1).sum())
    assert non_bg > 100, (
        f"legacy back-compat path didn't paint anything visible "
        f"({non_bg} non-bg pixels)"
    )
