"""Tests for the v4 outline-from-shape emitter helpers.

Phase 1.3 of plans/nhc_pure_ir_plan.md ships pure-data converters
from existing Room / cave / door geometry to :type:`OutlineT` and
:type:`CutT` instances. No emitter integration in this commit — the
helpers stand alone; future commits 1.4 – 1.14 wire them into
``_floor_layers.py`` so the per-shape ports each get their own
parity gate.

The tests pin per-helper coordinate output (rect / octagon / l_shape
go through explicit vertices; circle / pill go through the
descriptor variants), exercise the cave-path adapter, and pin the
door-feature → :enum:`CutStyle` mapping documented in plan §1.11.
"""

from __future__ import annotations

import math

from nhc.dungeon.model import (
    CircleShape, Level, LShape, OctagonShape, PillShape, Rect,
    Room, SurfaceType, TempleShape, Terrain, Tile,
)


CELL = 32  # mirrors nhc.rendering._svg_helpers.CELL


# ── outline_from_rect ─────────────────────────────────────────────


def test_outline_from_rect_room() -> None:
    """A 2x3 rect at tile (5, 7) becomes a 4-vertex closed polygon
    in pixel coords (rect.x * CELL, etc.). Polygon descriptor —
    cuts list starts empty."""
    from nhc.rendering._outline_helpers import outline_from_rect
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    rect = Rect(5, 7, 2, 3)
    out = outline_from_rect(rect)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None and len(out.vertices) == 4
    assert (out.vertices[0].x, out.vertices[0].y) == (160.0, 224.0)
    assert (out.vertices[1].x, out.vertices[1].y) == (224.0, 224.0)
    assert (out.vertices[2].x, out.vertices[2].y) == (224.0, 320.0)
    assert (out.vertices[3].x, out.vertices[3].y) == (160.0, 320.0)
    assert not out.cuts


# ── outline_from_octagon ──────────────────────────────────────────


def test_outline_from_octagon_room() -> None:
    """Octagon room becomes 8-vertex closed polygon. Clip size is
    max(1, min(w, h) // 3) * CELL — pinned per-vertex to lock the
    geometry against any future drift in the helper."""
    from nhc.rendering._outline_helpers import outline_from_octagon
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    rect = Rect(0, 0, 9, 6)
    room = Room(id="oct1", rect=rect, shape=OctagonShape())
    out = outline_from_octagon(room)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None and len(out.vertices) == 8

    clip = max(1, min(9, 6) // 3) * CELL  # 64
    expected = [
        (clip, 0),
        (9 * CELL - clip, 0),
        (9 * CELL, clip),
        (9 * CELL, 6 * CELL - clip),
        (9 * CELL - clip, 6 * CELL),
        (clip, 6 * CELL),
        (0, 6 * CELL - clip),
        (0, clip),
    ]
    for got, (ex, ey) in zip(out.vertices, expected):
        assert (got.x, got.y) == (float(ex), float(ey))


# ── outline_from_circle ───────────────────────────────────────────


def test_outline_from_circle_room() -> None:
    """Circle room becomes a Circle-descriptor outline: empty
    vertex list, cx / cy at the rect center, rx == ry from the
    diameter helper."""
    from nhc.rendering._outline_helpers import outline_from_circle
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    rect = Rect(0, 0, 7, 7)
    room = Room(id="circ1", rect=rect, shape=CircleShape())
    out = outline_from_circle(room)

    assert out.descriptorKind == OutlineKind.Circle
    assert out.closed is True
    assert not out.vertices
    assert out.cx == 7 * CELL / 2
    assert out.cy == 7 * CELL / 2
    expected_radius = CircleShape._diameter(rect) * CELL / 2
    assert out.rx == expected_radius
    assert out.ry == expected_radius


# ── outline_from_pill ─────────────────────────────────────────────


def test_outline_from_pill_room() -> None:
    """Pill room becomes a Pill-descriptor outline: cx / cy at the
    pill bbox center, rx / ry are half-extents of the pill bbox."""
    from nhc.rendering._outline_helpers import outline_from_pill
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    rect = Rect(2, 1, 9, 5)
    room = Room(id="pill1", rect=rect, shape=PillShape())
    out = outline_from_pill(room)

    assert out.descriptorKind == OutlineKind.Pill
    assert out.closed is True
    assert not out.vertices

    # Horizontal pill: bbox spans the full rect width, height
    # collapses to the pill's diameter (centred vertically).
    px, py = rect.x * CELL, rect.y * CELL
    pw, ph = rect.width * CELL, rect.height * CELL
    d = PillShape._diameter(rect)
    bx = px
    by = py + (ph - d * CELL) / 2.0
    bw = pw
    bh = d * CELL
    assert math.isclose(out.cx, bx + bw / 2.0)
    assert math.isclose(out.cy, by + bh / 2.0)
    assert math.isclose(out.rx, bw / 2.0)
    assert math.isclose(out.ry, bh / 2.0)


# ── outline_from_l_shape ──────────────────────────────────────────


def test_outline_from_l_shape_room() -> None:
    """L-shape room becomes a 6-vertex closed polygon. The notch
    cuts the requested corner; pin the vertex sequence so a later
    refactor of LShape's notch metric trips the test."""
    from nhc.rendering._outline_helpers import outline_from_l_shape
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    rect = Rect(1, 2, 6, 6)
    shape = LShape(corner="nw")
    room = Room(id="l1", rect=rect, shape=shape)
    out = outline_from_l_shape(room)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None and len(out.vertices) == 6

    notch = shape._notch_rect(rect)
    x0, y0 = rect.x, rect.y
    x1, y1 = rect.x2, rect.y2
    nx1, ny1 = notch.x2, notch.y2
    expected = [
        (nx1, y0), (x1, y0),
        (x1, y1), (x0, y1),
        (x0, ny1), (nx1, ny1),
    ]
    for got, (ex, ey) in zip(out.vertices, expected):
        assert (got.x, got.y) == (ex * CELL, ey * CELL)


# ── outline_from_temple ───────────────────────────────────────────


def test_outline_from_temple_room() -> None:
    """Temple-shape room becomes a closed polygon whose vertices
    match the existing TempleShape outline helper. Vertex count
    depends on the arc segment count, so just assert the helper
    produces SOME vertices and the closed flag is set; coordinate
    parity with the legacy helper is the contract."""
    from nhc.rendering._outline_helpers import outline_from_temple
    from nhc.rendering._room_outlines import _temple_vertices
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    rect = Rect(0, 0, 9, 9)
    shape = TempleShape(flat_side="south")
    room = Room(id="t1", rect=rect, shape=shape)
    out = outline_from_temple(room)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None and len(out.vertices) > 0

    # Same geometry as the legacy SVG outline helper.
    expected = _temple_vertices(shape, rect)
    assert len(out.vertices) == len(expected)
    for got, (ex, ey) in zip(out.vertices, expected):
        assert math.isclose(got.x, ex)
        assert math.isclose(got.y, ey)


# ── outline_from_polygon ─────────────────────────────────────────


def test_outline_from_polygon_carries_input_vertices() -> None:
    """A polygon's vertex list passes through to ``Outline.vertices``
    verbatim. Phase 1.12 introduces the helper for buildings: the
    ``_building_footprint_polygon_px`` helper returns pixel-space
    vertices for rect / octagon / circle / L-shape building footprints,
    and the new ExteriorWallOp emits these as a closed Polygon outline.
    The helper is shape-agnostic — buildings, future enclosures (1.14),
    and any other consumer with pre-computed polygon coords share the
    same wrapper rather than duplicating ``_polygon_outline`` calls.
    """
    from nhc.rendering._outline_helpers import outline_from_polygon
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    coords = [
        (32.0, 32.0), (320.0, 32.0),
        (320.0, 160.0), (32.0, 160.0),
    ]
    out = outline_from_polygon(coords)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None and len(out.vertices) == 4
    for got, (ex, ey) in zip(out.vertices, coords):
        assert (got.x, got.y) == (ex, ey)
    assert out.cuts == []


def test_outline_from_polygon_handles_arbitrary_vertex_count() -> None:
    """The helper round-trips polygons of any ring length — circle
    buildings polygonise to 24-gons, octagons to 8 vertices, L-shape
    buildings to 6 vertices. Pinning the helper for an 8-vertex octagon
    catches regressions where the wrapper truncates / reorders the
    input list.
    """
    from nhc.rendering._outline_helpers import outline_from_polygon

    coords = [
        (64.0, 0.0), (256.0, 0.0),
        (320.0, 64.0), (320.0, 256.0),
        (256.0, 320.0), (64.0, 320.0),
        (0.0, 256.0), (0.0, 64.0),
    ]
    out = outline_from_polygon(coords)

    assert len(out.vertices) == 8
    for got, (ex, ey) in zip(out.vertices, coords):
        assert (got.x, got.y) == (ex, ey)


# ── outline_from_cave ─────────────────────────────────────────────


def test_outline_from_cave_carries_input_vertices() -> None:
    """Cave outline carries the input vertex list verbatim (the
    centripetal Catmull-Rom curve is reproduced by the rasteriser
    at consumption time, per design/map_ir_v4.md §3 risks)."""
    from nhc.rendering._outline_helpers import outline_from_cave
    from nhc.rendering.ir._fb.OutlineKind import OutlineKind

    coords = [(10.0, 12.0), (40.0, 8.0), (60.0, 30.0), (32.0, 50.0)]
    out = outline_from_cave(coords)

    assert out.descriptorKind == OutlineKind.Polygon
    assert out.closed is True
    assert out.vertices is not None and len(out.vertices) == 4
    for got, (ex, ey) in zip(out.vertices, coords):
        assert (got.x, got.y) == (ex, ey)


# ── cuts_for_room_doors ──────────────────────────────────────────


def _make_room_with_door(
    door_feature: str, door_side: str = "north",
) -> tuple[Level, Room]:
    """Build a 7x7 level with a 2x2 rect room at (2, 2) and a
    single door tile flush to the room's edge per *door_side*."""
    level = Level.create_empty(
        id="floor1", name="test", depth=1, width=7, height=7,
    )
    rect = Rect(2, 2, 2, 2)
    room = Room(id="r1", rect=rect)
    level.rooms = [room]

    # Floor the room tiles.
    for ry in range(rect.y, rect.y2):
        for rx in range(rect.x, rect.x2):
            level.tiles[ry][rx] = Tile(terrain=Terrain.FLOOR)

    if door_side == "north":
        dx, dy = rect.x, rect.y - 1
    elif door_side == "south":
        dx, dy = rect.x, rect.y2
    elif door_side == "west":
        dx, dy = rect.x - 1, rect.y
    else:  # east
        dx, dy = rect.x2, rect.y
    level.tiles[dy][dx] = Tile(
        terrain=Terrain.FLOOR,
        feature=door_feature,
        door_side=door_side,
    )
    return level, room


def test_cuts_for_room_doors_resolves_door_position() -> None:
    """A door tile abutting a rect room produces one Cut on the
    room outline. Cut.start / Cut.end are the tile-edge endpoints
    in pixel coords; default door style is DoorWood."""
    from nhc.rendering._outline_helpers import cuts_for_room_doors
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    level, room = _make_room_with_door("door_closed", "north")
    cuts = cuts_for_room_doors(room, level)

    assert len(cuts) == 1
    cut = cuts[0]
    # Door tile is at (rect.x, rect.y - 1) = (2, 1); shared edge
    # with the room runs from (2, 2) to (3, 2) in tile coords —
    # i.e. (64, 64) to (96, 64) in pixels.
    assert (cut.start.x, cut.start.y) == (64.0, 64.0)
    assert (cut.end.x, cut.end.y) == (96.0, 64.0)
    assert cut.style == CutStyle.DoorWood


def test_cuts_for_room_doors_secret_maps_to_door_secret() -> None:
    """A door_secret tile resolves to CutStyle.DoorSecret."""
    from nhc.rendering._outline_helpers import cuts_for_room_doors
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    level, room = _make_room_with_door("door_secret", "south")
    cuts = cuts_for_room_doors(room, level)

    assert len(cuts) == 1
    assert cuts[0].style == CutStyle.DoorSecret


def test_cuts_for_room_doors_no_doors_returns_empty() -> None:
    """A room with no door tiles on its perimeter returns []."""
    from nhc.rendering._outline_helpers import cuts_for_room_doors

    level = Level.create_empty(
        id="floor1", name="test", depth=1, width=5, height=5,
    )
    rect = Rect(1, 1, 2, 2)
    room = Room(id="r1", rect=rect)
    for ry in range(rect.y, rect.y2):
        for rx in range(rect.x, rect.x2):
            level.tiles[ry][rx] = Tile(terrain=Terrain.FLOOR)

    assert cuts_for_room_doors(room, level) == []


def test_cuts_for_room_doors_open_locked_closed_all_door_wood() -> None:
    """door_open / door_closed / door_locked all map to DoorWood."""
    from nhc.rendering._outline_helpers import cuts_for_room_doors
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    for feature in ("door_open", "door_closed", "door_locked", "door"):
        level, room = _make_room_with_door(feature, "east")
        cuts = cuts_for_room_doors(room, level)
        assert len(cuts) == 1, f"expected 1 cut for {feature!r}"
        assert cuts[0].style == CutStyle.DoorWood, (
            f"{feature!r} should map to DoorWood"
        )


def test_cuts_for_room_doors_iron_maps_to_door_iron() -> None:
    """door_iron resolves to CutStyle.DoorIron.

    Forward-compat entry in :data:`_DOOR_FEATURE_TO_CUT_STYLE` — no
    current dungeon generator emits ``door_iron``, but the v4 IR
    reserves the style and the helper must round-trip it. Pinning the
    mapping here guards against future emitters dropping the value.
    """
    from nhc.rendering._outline_helpers import cuts_for_room_doors
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    level, room = _make_room_with_door("door_iron", "west")
    cuts = cuts_for_room_doors(room, level)

    assert len(cuts) == 1
    assert cuts[0].style == CutStyle.DoorIron


def test_cuts_for_room_doors_stone_maps_to_door_stone() -> None:
    """door_stone resolves to CutStyle.DoorStone.

    Forward-compat counterpart to :func:`...iron_maps_to_door_iron` —
    the schema reserves :enum:`CutStyle.DoorStone` for dungeon stone
    doors; the helper rounds it out so future generators can adopt
    the feature without re-walking ``_outline_helpers.py``.
    """
    from nhc.rendering._outline_helpers import cuts_for_room_doors
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    level, room = _make_room_with_door("door_stone", "north")
    cuts = cuts_for_room_doors(room, level)

    assert len(cuts) == 1
    assert cuts[0].style == CutStyle.DoorStone


def test_cuts_for_room_doors_position_at_tile_edges_per_side() -> None:
    """Cut.start / Cut.end land on the shared tile-edge endpoints
    in pixel coords, regardless of which side the door abuts.

    Pins the position contract for north / south / east / west doors
    on a 2x2 rect at (2, 2). Each side of the rect resolves to a
    single tile-edge segment in pixel coords:

    - north: (2*CELL, 2*CELL) → (3*CELL, 2*CELL)   (top edge of room tile (2,2))
    - south: (2*CELL, 4*CELL) → (3*CELL, 4*CELL)   (bottom edge of room tile (2,3))
    - west:  (2*CELL, 2*CELL) → (2*CELL, 3*CELL)   (left edge of room tile (2,2))
    - east:  (4*CELL, 2*CELL) → (4*CELL, 3*CELL)   (right edge of room tile (3,2))

    The endpoints are corners of the abutting room tile (NOT the
    midpoint of the edge) — the renderer breaks the wall stroke on
    the entire shared edge between room tile and door tile, which
    spans CELL pixels.
    """
    from nhc.rendering._outline_helpers import cuts_for_room_doors

    expected = {
        "north": ((2 * CELL, 2 * CELL), (3 * CELL, 2 * CELL)),
        "south": ((2 * CELL, 4 * CELL), (3 * CELL, 4 * CELL)),
        "west":  ((2 * CELL, 2 * CELL), (2 * CELL, 3 * CELL)),
        "east":  ((4 * CELL, 2 * CELL), (4 * CELL, 3 * CELL)),
    }
    for side, (exp_start, exp_end) in expected.items():
        level, room = _make_room_with_door("door_closed", side)
        cuts = cuts_for_room_doors(room, level)
        assert len(cuts) == 1, f"expected 1 cut on {side} side"
        cut = cuts[0]
        assert (cut.start.x, cut.start.y) == exp_start, (
            f"{side}: start mismatch (got "
            f"{(cut.start.x, cut.start.y)})"
        )
        assert (cut.end.x, cut.end.y) == exp_end, (
            f"{side}: end mismatch (got "
            f"{(cut.end.x, cut.end.y)})"
        )


# ── cuts_for_room_corridor_openings ─────────────────────────────


def _make_room_with_corridor(
    corridor_side: str,
) -> tuple[Level, Room]:
    """Build a 9x9 level with a 2x2 rect room at (3, 3) and a
    single corridor tile flush to the room's edge per *corridor_side*.

    The corridor tile has ``terrain=FLOOR``, ``surface_type=CORRIDOR``,
    and no door feature — these are the conditions the helper checks.
    """
    level = Level.create_empty(
        id="floor1", name="test", depth=1, width=9, height=9,
    )
    rect = Rect(3, 3, 2, 2)
    room = Room(id="r1", rect=rect)
    level.rooms = [room]

    for ry in range(rect.y, rect.y2):
        for rx in range(rect.x, rect.x2):
            level.tiles[ry][rx] = Tile(terrain=Terrain.FLOOR)

    if corridor_side == "north":
        cx, cy = rect.x, rect.y - 1
    elif corridor_side == "south":
        cx, cy = rect.x, rect.y2
    elif corridor_side == "west":
        cx, cy = rect.x - 1, rect.y
    else:  # east
        cx, cy = rect.x2, rect.y

    level.tiles[cy][cx] = Tile(
        terrain=Terrain.FLOOR,
        surface_type=SurfaceType.CORRIDOR,
    )
    return level, room


def test_cuts_for_room_corridor_openings_finds_north_neighbor() -> None:
    """A corridor tile at (room.x, room.y-1) produces one cut at
    the top edge of the adjacent room tile.

    Cut spans from (room.x * CELL, room.y * CELL) to
    ((room.x+1) * CELL, room.y * CELL) — the full tile-edge width.
    Style must be CutStyle.None_ (bare gap, no door visual).
    """
    from nhc.rendering._outline_helpers import (
        cuts_for_room_corridor_openings,
    )
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    level, room = _make_room_with_corridor("north")
    cuts = cuts_for_room_corridor_openings(room, level)

    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.style == CutStyle.None_
    # Corridor at (3, 2); shared edge with room tile (3, 3) is the
    # top edge of (3, 3): x in [3*CELL, 4*CELL], y = 3*CELL.
    assert (cut.start.x, cut.start.y) == (3 * CELL, 3 * CELL)
    assert (cut.end.x, cut.end.y) == (4 * CELL, 3 * CELL)


def test_cuts_for_room_corridor_openings_finds_all_four_directions() -> None:
    """Corridors abutting the room from N/S/E/W each produce one cut
    with correct tile-edge pixel coords and CutStyle.None_.

    Rect room at (3,3) width 2 height 2; corridor on each side in
    separate levels. Verifies all four cardinal directions are handled.
    """
    from nhc.rendering._outline_helpers import (
        cuts_for_room_corridor_openings,
    )
    from nhc.rendering.ir._fb.CutStyle import CutStyle

    rect = Rect(3, 3, 2, 2)
    # Expected tile-edge for the abutting room tile per direction:
    # north: room tile (3,3), top edge → y=3*CELL, x in [3,4]*CELL
    # south: room tile (3,4), bottom edge → y=5*CELL, x in [3,4]*CELL
    # west:  room tile (3,3), left edge  → x=3*CELL, y in [3,4]*CELL
    # east:  room tile (4,3), right edge → x=5*CELL, y in [3,4]*CELL
    expected = {
        "north": ((3 * CELL, 3 * CELL), (4 * CELL, 3 * CELL)),
        "south": ((3 * CELL, 5 * CELL), (4 * CELL, 5 * CELL)),
        "west":  ((3 * CELL, 3 * CELL), (3 * CELL, 4 * CELL)),
        "east":  ((5 * CELL, 3 * CELL), (5 * CELL, 4 * CELL)),
    }
    for side, (exp_start, exp_end) in expected.items():
        level, room = _make_room_with_corridor(side)
        cuts = cuts_for_room_corridor_openings(room, level)
        assert len(cuts) == 1, (
            f"{side}: expected 1 corridor cut, got {len(cuts)}"
        )
        cut = cuts[0]
        assert cut.style == CutStyle.None_, (
            f"{side}: cut style must be None_, got {cut.style}"
        )
        assert (cut.start.x, cut.start.y) == exp_start, (
            f"{side}: start mismatch (got "
            f"{(cut.start.x, cut.start.y)})"
        )
        assert (cut.end.x, cut.end.y) == exp_end, (
            f"{side}: end mismatch (got "
            f"{(cut.end.x, cut.end.y)})"
        )


def test_cuts_for_room_corridor_openings_skips_void_neighbors() -> None:
    """A non-walkable / void tile adjacent to the room produces zero
    cuts.

    Only corridor tiles (walkable + surface_type == CORRIDOR, no door
    feature) should produce cuts. VOID tiles have terrain != FLOOR so
    ``_is_floor`` returns False and no cut is emitted.
    """
    from nhc.rendering._outline_helpers import (
        cuts_for_room_corridor_openings,
    )

    level = Level.create_empty(
        id="floor1", name="test", depth=1, width=7, height=7,
    )
    rect = Rect(2, 2, 2, 2)
    room = Room(id="r1", rect=rect)
    level.rooms = [room]
    for ry in range(rect.y, rect.y2):
        for rx in range(rect.x, rect.x2):
            level.tiles[ry][rx] = Tile(terrain=Terrain.FLOOR)

    # All neighbors are VOID (default); no cuts expected.
    cuts = cuts_for_room_corridor_openings(room, level)
    assert cuts == [], (
        "VOID neighbors must not produce corridor cuts"
    )


def test_cuts_for_room_corridor_openings_skips_door_tiles() -> None:
    """A door tile adjacent to the room produces zero corridor cuts.

    Door tiles are walkable (terrain=FLOOR) but ``cuts_for_room_doors``
    handles them — :func:`cuts_for_room_corridor_openings` must skip
    them so the two helpers are mutually exclusive on tile-edge
    positions. A tile with a door feature is excluded by checking that
    its feature is not in the door-feature set.
    """
    from nhc.rendering._outline_helpers import (
        cuts_for_room_corridor_openings,
    )

    level, room = _make_room_with_door("door_closed", "north")
    # The door tile is walkable (terrain=FLOOR) but has a door feature;
    # it also lacks surface_type=CORRIDOR. Either check suffices;
    # the helper must produce zero cuts for door tiles.
    cuts = cuts_for_room_corridor_openings(room, level)
    assert cuts == [], (
        "door tiles must not produce corridor-opening cuts "
        "(cuts_for_room_doors handles doors)"
    )
