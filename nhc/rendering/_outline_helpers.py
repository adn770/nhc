"""Outline / Cut emitter helpers for the v4e IR.

Pure-data converters from existing :class:`nhc.dungeon.model.Rect` /
:class:`Room` / cave coordinate / door geometry to :class:`OutlineT`
and :class:`CutT` instances.

The helpers are deliberately narrow:

- ``outline_from_rect`` / ``outline_from_octagon`` /
  ``outline_from_l_shape`` / ``outline_from_temple`` produce
  Polygon-descriptor outlines with explicit pixel-space vertices.
- ``outline_from_circle`` / ``outline_from_pill`` produce the
  Circle / Pill descriptor variants — the rasterisers reproduce
  these via their native primitives at consumption time.
- ``outline_from_cave`` carries the cave's vertex list verbatim;
  both rasterisers reproduce the centripetal Catmull-Rom curve
  via ``centripetal_bezier_cps``.
- ``cuts_for_room_doors`` walks a room's edge tiles, finds
  neighbouring door features, and emits one :class:`CutT` per door
  with start / end at the shared tile-edge midpoints in pixel
  coords. ``CutStyle`` is picked from the door feature string per
  the door-feature → CutStyle mapping below.
- ``cuts_for_enclosure_gates`` resolves enclosure gate triples
  ``(edge_idx, t_center, half_px)`` to pixel-space Cut pairs.

All vertex coords are in pixel space (tile coord × CELL); no
PADDING is applied — that is the renderer's job (the legacy SVG
output also leaves padding to the wrapping ``<svg>`` element).
"""

from __future__ import annotations

import math
from typing import Any

from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level, LShape,
    OctagonShape, PillShape, Rect, Room, SurfaceType, TempleShape,
    Terrain,
)
from nhc.rendering._room_outlines import (
    _hybrid_vertices, _intersect_outline, _temple_vertices,
)
from nhc.rendering._svg_helpers import _find_doorless_openings
from nhc.rendering.ir._fb.Cut import CutT
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.Vec2 import Vec2T


CELL = 32  # mirrors nhc.rendering._svg_helpers.CELL

# Mapping from a tile.feature string to the v4 :enum:`CutStyle`.
# Pinned per plans/nhc_pure_ir_plan.md §1.11 — door_secret looks
# like a wall on the static map; door / door_open / door_closed /
# door_locked all paint as wooden doors. door_iron is forward-compat
# (no current generator emits it; defensive entry for future use).
_DOOR_FEATURE_TO_CUT_STYLE: dict[str, int] = {
    "door": CutStyle.DoorWood,
    "door_open": CutStyle.DoorWood,
    "door_closed": CutStyle.DoorWood,
    "door_locked": CutStyle.DoorWood,
    "door_secret": CutStyle.DoorSecret,
    "door_iron": CutStyle.DoorIron,
    "door_stone": CutStyle.DoorStone,
}

_DOOR_FEATURES: frozenset[str] = frozenset(_DOOR_FEATURE_TO_CUT_STYLE)


def _vec2(x: float, y: float) -> Vec2T:
    """Build a Vec2T at the given pixel coords."""
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _polygon_outline(
    vertices: list[tuple[float, float]],
    *,
    closed: bool = True,
) -> OutlineT:
    """Build a Polygon-descriptor OutlineT from explicit vertices.

    Vertices are pixel-space; cuts default to the empty list (the
    emitter populates them later via :func:`cuts_for_room_doors`).
    """
    out = OutlineT()
    out.descriptorKind = OutlineKind.Polygon
    out.closed = closed
    out.vertices = [_vec2(x, y) for x, y in vertices]
    return out


# ── Polygon-descriptor helpers ─────────────────────────────────


def outline_from_rect(rect: Rect) -> OutlineT:
    """Convert a :class:`Rect` into a 4-vertex closed polygon.

    Vertices are emitted clockwise starting at the top-left corner.
    """
    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    return _polygon_outline([
        (px, py),
        (px + pw, py),
        (px + pw, py + ph),
        (px, py + ph),
    ])


def outline_from_octagon(room: Room) -> OutlineT:
    """Convert an octagon room into an 8-vertex closed polygon.

    Reproduces the vertex ordering of
    :func:`_room_outlines._room_svg_outline`'s octagon branch:
    clip = ``max(1, min(w, h) // 3) * CELL``.
    """
    rect = room.rect
    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    clip = max(1, min(rect.width, rect.height) // 3) * CELL
    return _polygon_outline([
        (px + clip, py),
        (px + pw - clip, py),
        (px + pw, py + clip),
        (px + pw, py + ph - clip),
        (px + pw - clip, py + ph),
        (px + clip, py + ph),
        (px, py + ph - clip),
        (px, py + clip),
    ])


def outline_from_l_shape(room: Room) -> OutlineT:
    """Convert an L-shape room into a 6-vertex closed polygon.

    Reproduces the vertex ordering of
    :func:`_room_outlines._room_svg_outline`'s ``LShape`` branch.
    """
    rect = room.rect
    shape = room.shape
    if not isinstance(shape, LShape):
        raise TypeError(
            f"outline_from_l_shape: expected LShape, got "
            f"{type(shape).__name__}"
        )

    notch = shape._notch_rect(rect)
    x0, y0 = rect.x, rect.y
    x1, y1 = rect.x2, rect.y2
    nx0, ny0 = notch.x, notch.y
    nx1, ny1 = notch.x2, notch.y2

    def _tp(tx: int, ty: int) -> tuple[float, float]:
        return (tx * CELL, ty * CELL)

    if shape.corner == "nw":
        verts = [
            _tp(nx1, y0), _tp(x1, y0),
            _tp(x1, y1), _tp(x0, y1),
            _tp(x0, ny1), _tp(nx1, ny1),
        ]
    elif shape.corner == "ne":
        verts = [
            _tp(x0, y0), _tp(nx0, y0),
            _tp(nx0, ny1), _tp(x1, ny1),
            _tp(x1, y1), _tp(x0, y1),
        ]
    elif shape.corner == "sw":
        verts = [
            _tp(x0, y0), _tp(x1, y0),
            _tp(x1, y1), _tp(nx1, y1),
            _tp(nx1, ny0), _tp(x0, ny0),
        ]
    else:  # "se"
        verts = [
            _tp(x0, y0), _tp(x1, y0),
            _tp(x1, ny0), _tp(nx0, ny0),
            _tp(nx0, y1), _tp(x0, y1),
        ]
    return _polygon_outline(verts)


def outline_from_cross(room: Room) -> OutlineT:
    """Convert a cross-shape room into a 12-vertex closed polygon.

    Mirrors :func:`_room_outlines._room_svg_outline`'s ``CrossShape``
    branch: traces the + outline clockwise, with bar widths derived
    from ``max(2, dim // 3)`` so the polygon is byte-identical to
    the legacy SVG ``<polygon points>`` element.
    """
    rect = room.rect
    shape = room.shape
    if not isinstance(shape, CrossShape):
        raise TypeError(
            f"outline_from_cross: expected CrossShape, got "
            f"{type(shape).__name__}"
        )

    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    bar_w = max(2, rect.width // 3) * CELL
    bar_h = max(2, rect.height // 3) * CELL
    cx_tile = rect.x + rect.width // 2
    cy_tile = rect.y + rect.height // 2
    vl = (cx_tile - max(2, rect.width // 3) // 2) * CELL
    vr = vl + bar_w
    ht = (cy_tile - max(2, rect.height // 3) // 2) * CELL
    hb = ht + bar_h
    verts = [
        (vl, py), (vr, py),
        (vr, ht), (px + pw, ht),
        (px + pw, hb), (vr, hb),
        (vr, py + ph), (vl, py + ph),
        (vl, hb), (px, hb),
        (px, ht), (vl, ht),
    ]
    return _polygon_outline(verts)


def outline_from_hybrid(room: Room) -> OutlineT:
    """Convert a hybrid room into a tessellated closed polygon.

    Hybrid outlines combine a curved sub-shape with a rect side; the
    legacy :func:`_room_outlines._hybrid_svg_outline` emits an SVG
    ``<path>`` with arc commands. v4 ships pure data, so the v4
    outline is the polygonised vertex list — the same dense polyline
    :func:`_room_outlines._hybrid_vertices` produces. The Rust
    consumer rasterises the polyline; the Python ExteriorWallOp
    consumer feeds it through ``_walk_polygon_with_cuts`` so the
    gapped wall pipeline (corridor openings) reuses the existing
    polygon-with-cuts machinery.

    The legacy ``smoothFillSvg`` arc-path FILL is unaffected by this
    helper — it stays on the legacy SVG-string path until 1.20c (or
    later) migrates the hybrid fill to a FloorOp with an arc-aware
    descriptor.
    """
    rect = room.rect
    shape = room.shape
    if not isinstance(shape, HybridShape):
        raise TypeError(
            f"outline_from_hybrid: expected HybridShape, got "
            f"{type(shape).__name__}"
        )
    return _polygon_outline(_hybrid_vertices(shape, rect))


def outline_from_temple(room: Room) -> OutlineT:
    """Convert a temple-shape room into a closed polygon.

    Defers to the existing :func:`_room_outlines._temple_vertices`
    helper for the exact arc-segment discretisation; the v4
    emitter consumes the same vertex list the legacy SVG path
    walks.
    """
    rect = room.rect
    shape = room.shape
    if not isinstance(shape, TempleShape):
        raise TypeError(
            f"outline_from_temple: expected TempleShape, got "
            f"{type(shape).__name__}"
        )
    return _polygon_outline(_temple_vertices(shape, rect))


# ── Descriptor-variant helpers ─────────────────────────────────


def outline_from_circle(room: Room) -> OutlineT:
    """Convert a circle room into a Circle-descriptor outline.

    ``cx`` / ``cy`` is the rect bounding-box centre; ``rx == ry``
    is the diameter (per :meth:`CircleShape._diameter`) divided by
    two. Vertices and cuts default to empty lists; the rasterisers
    reproduce the circle via their native primitives.
    """
    rect = room.rect
    shape = room.shape
    if not isinstance(shape, CircleShape):
        raise TypeError(
            f"outline_from_circle: expected CircleShape, got "
            f"{type(shape).__name__}"
        )

    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    radius = shape._diameter(rect) * CELL / 2.0

    out = OutlineT()
    out.descriptorKind = OutlineKind.Circle
    out.closed = True
    out.vertices = []
    out.cx = float(px + pw / 2)
    out.cy = float(py + ph / 2)
    out.rx = float(radius)
    out.ry = float(radius)
    return out


def outline_from_pill(room: Room) -> OutlineT:
    """Convert a pill room into a Pill-descriptor outline.

    The rounded-rect bbox is the pill's bounding box: full-width
    along the long axis, collapsed to the pill diameter on the
    short axis. ``cx`` / ``cy`` is the bbox centre; ``rx`` / ``ry``
    is the bbox half-extent on each axis (the rasteriser uses
    these to size the rounded corners and the inner straight
    section).
    """
    rect = room.rect
    shape = room.shape
    if not isinstance(shape, PillShape):
        raise TypeError(
            f"outline_from_pill: expected PillShape, got "
            f"{type(shape).__name__}"
        )

    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    d = shape._diameter(rect)

    if rect.width >= rect.height:
        bx = px
        by = py + (ph - d * CELL) / 2.0
        bw = pw
        bh = d * CELL
    else:
        bx = px + (pw - d * CELL) / 2.0
        by = py
        bw = d * CELL
        bh = ph

    out = OutlineT()
    out.descriptorKind = OutlineKind.Pill
    out.closed = True
    out.vertices = []
    out.cx = float(bx + bw / 2.0)
    out.cy = float(by + bh / 2.0)
    out.rx = float(bw / 2.0)
    out.ry = float(bh / 2.0)
    return out


# ── Cave outline ───────────────────────────────────────────────


def outline_from_cave(
    coords: list[tuple[float, float]],
) -> OutlineT:
    """Carry a cave's traced vertex list as a closed polygon.

    The Catmull-Rom smoothing the legacy
    :func:`_cave_geometry._smooth_closed_path` performs is a pure
    function of the same vertex list, so the v4 emitter ships only
    the vertices and lets the rasterisers reproduce the curve.
    Coords are already in pixel space (per
    :func:`_trace_cave_boundary_coords`).
    """
    return _polygon_outline(list(coords))


# ── Generic polygon outline (buildings, enclosures) ────────────


def outline_from_polygon(
    coords: list[tuple[float, float]],
    *,
    closed: bool = True,
) -> OutlineT:
    """Wrap a pre-computed pixel-space polygon as a closed Outline.

    Phase 1.12 introduces this helper for buildings — the existing
    :func:`nhc.rendering.ir_emitter._building_footprint_polygon_px`
    returns the building footprint as a list of ``(x, y)`` pixel-coord
    vertices, and the new ExteriorWallOp ships them as a closed Polygon
    outline. The helper is shape-agnostic so future commits (1.14
    enclosures, etc.) can reuse it for any consumer that already has
    polygon coords in pixel space.

    Vertices are passed through verbatim — no closing duplicate, no
    reordering. ``closed`` defaults to True (the typical building /
    enclosure case); future open-polyline consumers (1.13 partition
    outlines) can flip it.
    """
    return _polygon_outline(list(coords), closed=closed)


# ── Door cut resolution ────────────────────────────────────────


def cuts_for_room_doors(
    room: Room, level: Level,
) -> list[CutT]:
    """Walk the room's perimeter and emit one Cut per door tile.

    A door is a tile whose ``feature`` is in
    :data:`_DOOR_FEATURES` and whose position is adjacent to one
    of the room's floor tiles (sharing an axis-aligned edge).
    Cut.start / Cut.end are the two pixel-space endpoints of the
    shared tile edge between the room tile and the door tile;
    Cut.style is picked via :data:`_DOOR_FEATURE_TO_CUT_STYLE`.

    The emitter populates the resulting cuts on
    :type:`ExteriorWallOp.cuts`.
    """
    floor = room.floor_tiles()
    cuts: list[CutT] = []

    for fx, fy in floor:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = fx + dx, fy + dy
            if (nx, ny) in floor:
                continue
            tile = level.tile_at(nx, ny)
            if tile is None or tile.feature not in _DOOR_FEATURES:
                continue

            # Pixel coords of the shared tile edge between (fx, fy)
            # and (nx, ny). For each cardinal neighbour direction
            # the edge is the line on the appropriate side of the
            # room tile.
            if dy == -1:  # door is north of the room tile
                start = (fx * CELL, fy * CELL)
                end = ((fx + 1) * CELL, fy * CELL)
            elif dy == 1:  # south
                start = (fx * CELL, (fy + 1) * CELL)
                end = ((fx + 1) * CELL, (fy + 1) * CELL)
            elif dx == -1:  # west
                start = (fx * CELL, fy * CELL)
                end = (fx * CELL, (fy + 1) * CELL)
            else:  # east, dx == 1
                start = ((fx + 1) * CELL, fy * CELL)
                end = ((fx + 1) * CELL, (fy + 1) * CELL)

            cut = CutT()
            cut.start = _vec2(*start)
            cut.end = _vec2(*end)
            cut.style = _DOOR_FEATURE_TO_CUT_STYLE[tile.feature]
            cuts.append(cut)

    return cuts


# ── Enclosure gate cut resolution ─────────────────────────────


def cuts_for_enclosure_gates(
    polygon_px: list[tuple[float, float]],
    gates: list[tuple[int, float, float]],
    cut_style: int,
) -> list[CutT]:
    """Resolve enclosure gate triples to pixel-space Cut pairs.

    Each gate is described as ``(edge_idx, t_center, half_px)``:
    - ``polygon_px[edge_idx]`` and ``polygon_px[(edge_idx+1) % n]``
      are the edge endpoints in pixel space.
    - ``t_center`` is the parametric position along that edge (0..1).
    - ``half_px`` is half the gate width in pixel space.

    The gate's pixel center is ``lerp(p0, p1, t_center)``. The cut
    start / end are ``center ± half_px * unit_dir`` along the edge.

    ``cut_style`` is the v4e :class:`CutStyle` to stamp on each gate
    (typically ``CutStyle.WoodGate`` or ``CutStyle.PortcullisGate``).

    Used by :func:`emit_site_enclosure` to populate
    :type:`ExteriorWallOp.cuts` for palisade / fortification
    enclosures. Mirrors the door-cut resolution approach of
    :func:`cuts_for_building_doors` / :func:`cuts_for_room_doors` but
    operates on parametric edge geometry rather than tile adjacency.
    """
    n = len(polygon_px)
    cuts: list[CutT] = []

    for edge_idx, t_center, half_px in gates:
        ax, ay = polygon_px[edge_idx]
        bx, by = polygon_px[(edge_idx + 1) % n]
        dx, dy = bx - ax, by - ay
        edge_len = math.sqrt(dx * dx + dy * dy)
        if edge_len == 0.0:
            continue
        # Unit vector along the edge.
        ux, uy = dx / edge_len, dy / edge_len
        # Gate centre in pixel space.
        cx = ax + dx * t_center
        cy = ay + dy * t_center
        # Start and end of the cut.
        start = (cx - ux * half_px, cy - uy * half_px)
        end = (cx + ux * half_px, cy + uy * half_px)

        cut = CutT()
        cut.start = _vec2(*start)
        cut.end = _vec2(*end)
        cut.style = cut_style
        cuts.append(cut)

    return cuts


# ── Building door cut resolution ───────────────────────────────


def cuts_for_building_doors(
    building: Any, level: Any,
) -> list[CutT]:
    """Walk the building's perimeter and emit one Cut per door tile.

    Mirrors :func:`cuts_for_room_doors` but for :class:`Building`
    instances. Buildings carry geometry on ``base_shape`` /
    ``base_rect`` rather than the :class:`Room`-style ``floor_tiles``
    method, so the helper derives the floor-tile set via
    :meth:`RoomShape.floor_tiles` directly. Once a door tile is found,
    the Cut's start / end / style resolution is identical to the
    room helper — :func:`cuts_for_room_doors`'s walker is reused
    after building a Room-like adapter object so the door-side /
    pixel-edge logic stays in one place.

    Used by :func:`emit_building_walls` to populate
    :type:`ExteriorWallOp.cuts` for masonry buildings.
    """
    from types import SimpleNamespace

    floor = building.base_shape.floor_tiles(building.base_rect)
    adapter = SimpleNamespace(floor_tiles=lambda: floor)
    return cuts_for_room_doors(adapter, level)  # type: ignore[arg-type]


# ── Doorless-gap cut resolution (smooth rooms) ─────────────────


def cuts_for_doorless_openings(
    room: Room, level: Level,
) -> list[CutT]:
    """Walk the room's perimeter and emit one ``Cut`` per doorless
    corridor opening.

    A doorless opening is a corridor tile (``surface_type ==
    CORRIDOR``) that abuts the room without a door feature in
    between. The legacy renderer lifts these via
    :func:`_outline_with_gaps`, intersecting the corridor's two side
    walls with the room outline at points ``hit_a`` / ``hit_b``; the
    arc / polygon edge between those points is the gap. The v4
    structured form represents the same gap as a single
    :class:`CutT` with ``start = hit_a``, ``end = hit_b``,
    ``style = CutStyle.None_`` — the renderer skips the stroke for
    that interval.

    Used by :func:`_emit_walls_and_floors_ir` for smooth-shape rooms
    (Phase 1.9). Rect rooms have no doorless gaps in their renderer
    path — corridors meet rect rooms via tile-edge segments handled
    by the wall-segment walker — so this helper is only invoked for
    OctagonShape / LShape / TempleShape / CircleShape / PillShape
    rooms.

    Returns an empty list for shapes that lack a meaningful
    intersection (the legacy ``_intersect_outline`` returns ``None``
    for unsupported shapes — we skip those silently).
    """
    shape = room.shape
    rect = room.rect
    openings = _find_doorless_openings(room, level)
    cuts: list[CutT] = []

    for fx, fy, cx, cy in openings:
        dx, dy = cx - fx, cy - fy
        if dy != 0:  # N/S corridor → vertical walls
            wall_a = (fx * CELL, fy * CELL if dy == -1
                      else (fy + 1) * CELL)
            wall_b = ((fx + 1) * CELL, wall_a[1])
        else:  # E/W corridor → horizontal walls
            wall_a = (fx * CELL if dx == -1
                      else (fx + 1) * CELL, fy * CELL)
            wall_b = (wall_a[0], (fy + 1) * CELL)

        hit_a = _intersect_outline(shape, rect, wall_a, dx, dy)
        hit_b = _intersect_outline(shape, rect, wall_b, dx, dy)
        if hit_a is None or hit_b is None:
            continue

        cut = CutT()
        cut.start = _vec2(*hit_a)
        cut.end = _vec2(*hit_b)
        cut.style = CutStyle.None_
        cuts.append(cut)

    return cuts


# ── Rect-room corridor-opening cut resolution ──────────────────


def cuts_for_room_corridor_openings(
    room: Room, level: Level,
) -> list[CutT]:
    """Walk a rect room's perimeter and emit one Cut per corridor tile.

    Walks each floor tile of the room and checks its four cardinal
    neighbours. For each neighbour that is a corridor tile
    (``surface_type == SurfaceType.CORRIDOR``, ``terrain ==
    Terrain.FLOOR``, no door feature), emits one :class:`CutT` whose
    ``start`` / ``end`` are the pixel-space endpoints of the shared
    tile edge between the room tile and the corridor tile. ``style``
    is ``CutStyle.None_`` — a bare gap with no door visual.

    The legacy ``wall_segments`` algorithm skips wall emission for any
    walkable neighbour (``_is_floor`` or ``_is_door``); the door case
    is already encoded by :func:`cuts_for_room_doors`. This helper
    encodes the corridor case so the two helpers together cover every
    position where ``wall_segments`` would skip a segment on a rect
    room's perimeter. Phase 1.16b-3's consumer can then walk the rect
    outline and break the stroke at *both* sets of cuts to reproduce
    byte-equivalent walls to legacy.

    Symmetric to :func:`cuts_for_doorless_openings` for smooth rooms
    (Phase 1.9), which uses intersection geometry for non-axis-aligned
    outlines. Rect rooms have axis-aligned edges so the tile-edge
    pixel coords are computed directly — no intersection needed.

    Door tiles are excluded: ``cuts_for_room_doors`` handles them.
    The two helpers are mutually exclusive — a tile with a door feature
    produces a door-flavoured cut from :func:`cuts_for_room_doors` and
    zero cuts here.
    """
    floor = room.floor_tiles()
    cuts: list[CutT] = []

    for fx, fy in floor:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = fx + dx, fy + dy
            if (nx, ny) in floor:
                continue
            nb = level.tile_at(nx, ny)
            if (nb is None
                    or nb.surface_type != SurfaceType.CORRIDOR
                    or nb.terrain != Terrain.FLOOR
                    or (nb.feature is not None
                        and nb.feature in _DOOR_FEATURES)):
                continue

            # Pixel coords of the shared tile edge between the room
            # tile (fx, fy) and the corridor tile (nx, ny).
            if dy == -1:  # corridor is north of the room tile
                start = (fx * CELL, fy * CELL)
                end = ((fx + 1) * CELL, fy * CELL)
            elif dy == 1:  # south
                start = (fx * CELL, (fy + 1) * CELL)
                end = ((fx + 1) * CELL, (fy + 1) * CELL)
            elif dx == -1:  # west
                start = (fx * CELL, fy * CELL)
                end = (fx * CELL, (fy + 1) * CELL)
            else:  # east, dx == 1
                start = ((fx + 1) * CELL, fy * CELL)
                end = ((fx + 1) * CELL, (fy + 1) * CELL)

            cut = CutT()
            cut.start = _vec2(*start)
            cut.end = _vec2(*end)
            cut.style = CutStyle.None_
            cuts.append(cut)

    return cuts
