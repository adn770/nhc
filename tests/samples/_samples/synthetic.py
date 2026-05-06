"""Synthetic NIR samples — surgical isolation for the painter
matrix. Each sample hand-builds a minimum-viable :class:`Level`
with one room (or a small set) and renders it through
``build_floor_ir`` so the IR pipeline is the production code path
but the input is controlled.

The matrix is per-shape × per-style × per-context so a reviewer
can flip side-by-side images and identify:

* corner / curve bleeding (rect vs octagon vs circle vs pill).
* per-context portability (stone floor at site / dungeon-room /
  building floor — same primitive, three consumers).
* group-opacity overlap correctness (hatch + shadow at high
  density).

Catalog organisation mirrors the directory tree under
``debug/samples/synthetic/``.
"""

from __future__ import annotations

from nhc.dungeon.model import (
    CircleShape, Level, LevelMetadata, OctagonShape, PillShape,
    RectShape, Rect, Room, RoomShape, Terrain, Tile,
)
from nhc.rendering.ir_emitter import build_floor_ir

from ._core import BuildResult, CATALOG, SampleSpec


# ── Synthetic level builders ───────────────────────────────────────


def _stamp_room_floor(level: Level, room: Room) -> None:
    """Mark every tile in ``room.floor_tiles()`` as FLOOR. Tiles
    outside the room remain VOID (the level was created empty)."""
    for x, y in room.floor_tiles():
        if level.in_bounds(x, y):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)


def _single_room_level(
    shape: RoomShape,
    *,
    rect: Rect,
    canvas: tuple[int, int] = (24, 18),
    theme: str = "dungeon",
    room_id: str = "room.1",
) -> Level:
    """Empty level with one room of ``shape`` placed at ``rect``.

    The canvas is sized to leave ~3 tiles of margin around the
    room so wall strokes have room to render without clipping at
    the canvas edge.
    """
    w, h = canvas
    level = Level.create_empty(
        id="synthetic", name="synthetic", depth=1,
        width=w, height=h,
    )
    level.metadata = LevelMetadata(theme=theme)
    room = Room(id=room_id, rect=rect, shape=shape)
    level.rooms.append(room)
    _stamp_room_floor(level, room)
    return level


# ── Shape-builder helpers ──────────────────────────────────────────
#
# Each returns a (shape, rect, canvas) tuple sized so the room sits
# in the centre with ~3-tile margins. The rect dimensions are
# chosen so each shape's characteristic geometry is clearly
# visible (chamfer corners on octagon, curves on circle / pill).


def _rect_room() -> tuple[RoomShape, Rect, tuple[int, int]]:
    return RectShape(), Rect(x=4, y=3, width=12, height=10), (20, 16)


def _octagon_room() -> tuple[RoomShape, Rect, tuple[int, int]]:
    return OctagonShape(), Rect(x=4, y=3, width=12, height=10), (20, 16)


def _circle_room() -> tuple[RoomShape, Rect, tuple[int, int]]:
    return CircleShape(), Rect(x=4, y=3, width=11, height=11), (19, 17)


def _pill_room() -> tuple[RoomShape, Rect, tuple[int, int]]:
    return PillShape(), Rect(x=4, y=4, width=14, height=8), (22, 16)


_SHAPES = {
    "rect":    _rect_room,
    "octagon": _octagon_room,
    "circle":  _circle_room,
    "pill":    _pill_room,
}


def _single_shape_result(
    shape_key: str, *, theme: str, seed: int,
) -> BuildResult:
    """Build IR for a single-room level of the given shape."""
    shape, rect, canvas = _SHAPES[shape_key]()
    level = _single_room_level(
        shape, rect=rect, canvas=canvas, theme=theme,
    )
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


# ── Group-opacity overlap stress ───────────────────────────────────
#
# Group-opacity (begin_group / end_group) is the load-bearing
# Phase 5.10 mechanism: overlapping translucent stamps inside a
# group composite at the group's opacity, not by per-element alpha
# multiplication. The pre-Phase-5.10 behaviour over-darkened
# overlap regions; the v4e Painter trait fixes this. These samples
# render dense overlap configurations so any regression surfaces
# as visibly darker overlap in the same folder.
#
# The simplest way to surface this is to render rooms tightly
# packed so corridor halos (hatch) overlap and shadow rects align
# along shared edges.


def _twin_rooms_level(theme: str = "dungeon") -> Level:
    """Two adjacent rect rooms sharing a wall; the hatch halo
    overlaps along the shared edge."""
    level = Level.create_empty(
        id="synthetic", name="synthetic", depth=1,
        width=24, height=12,
    )
    level.metadata = LevelMetadata(theme=theme)
    rooms = [
        Room(id="room.1", rect=Rect(x=2, y=2, width=8, height=8),
             shape=RectShape()),
        Room(id="room.2", rect=Rect(x=12, y=2, width=8, height=8),
             shape=RectShape()),
    ]
    for r in rooms:
        level.rooms.append(r)
        _stamp_room_floor(level, r)
    return level


def _twin_rooms_result(seed: int, *, theme: str = "dungeon") -> BuildResult:
    level = _twin_rooms_level(theme=theme)
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


CATALOG.extend([
    SampleSpec(
        name="twin_rooms_hatch_halo",
        category="synthetic/group_opacity",
        description=(
            "Two adjacent rect rooms — the hatch halo and shadow "
            "envelope overlap between them. Verifies that the "
            "Painter's begin_group/end_group offscreen-buffer "
            "compositing keeps overlap pixels at the group's "
            "opacity (≈128 for 0.5) rather than the per-element "
            "double-darkened (~64) value."
        ),
        params={"layout": "twin_rect_adjacent"},
        build=lambda s: _twin_rooms_result(s),
        seeds=(7,),
    ),
])


# ── Region kind sampler ────────────────────────────────────────────
#
# v4e introduces five region kinds: Dungeon, Building, Cave, Site,
# Enclosure (plus Corridor). Every paint op resolves through
# region_ref → Region.outline. These samples render one region
# per kind alongside a minimal floor + perimeter so the
# region_ref dispatch is visible.
#
# The Dungeon / Cave / Building / Site / Enclosure cases are
# covered by the floors / generators / sites samples already.
# The Corridor region is unique — it's a multi-ring outline
# (corridor body + interior holes for adjacent rooms) — and the
# twin-rooms layout above with a connecting corridor exercises
# it. We keep the catalog focused on the matrix that doesn't
# already get covered.


__all__ = []
