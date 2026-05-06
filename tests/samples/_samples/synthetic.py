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


# ── Decorator matrix: each decorator on each shape ─────────────────
#
# The 7 decorator variants (cobblestone, brick, flagstone,
# opus_romano, field_stone, cart_tracks, ore_deposit) each ride
# on a base floor. The risk surface is bleeding past the
# perimeter on octagon (chamfered corners) and circle (curves).
# Each decorator sample shows the same shape rendering with the
# decorator overlaid; flipping side-by-side images surfaces any
# per-shape edge artefact.
#
# The dungeon themer applies decorators automatically by default;
# for the synthetic isolation we inject the room metadata that
# triggers the matching decorator. The exact metadata key set
# lives in nhc.rendering._floor_layers but we route through the
# theme override to keep the sample minimal.


# Tag the room with the decorator type via a tag the floor-detail
# emitter consumes. The actual mapping lives in the cobblestone /
# brick / etc. emitters in `nhc/rendering/`.


_DECORATOR_TAG_FOR_VARIANT = {
    "cobblestone": "STREET",
    "brick": "BRICK",
    "flagstone": "FLAGSTONE",
    "opus_romano": "OPUS_ROMANO",
    "field_stone": "FIELD_STONE",
    "cart_tracks": "MINE_TRACKS",
    "ore_deposit": "ORE_DEPOSIT",
}


def _decorator_result(
    variant: str, shape_key: str, *, seed: int,
) -> BuildResult:
    """Build a single-room level with the given decorator tag."""
    shape, rect, canvas = _SHAPES[shape_key]()
    level = _single_room_level(
        shape, rect=rect, canvas=canvas, theme="dungeon",
    )
    # The room.tags carry the decorator hint that
    # _floor_layers.py picks up to emit the matching DecoratorOp
    # variant. Tags are case-insensitive at the consumer.
    tag = _DECORATOR_TAG_FOR_VARIANT[variant]
    level.rooms[0].tags = [tag]
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


for _variant in _DECORATOR_TAG_FOR_VARIANT:
    for _shape_key in ("rect", "octagon", "circle"):
        CATALOG.append(SampleSpec(
            name=f"on_{_shape_key}",
            category=f"synthetic/decorators/{_variant}",
            description=(
                f"{_variant} decorator on a {_shape_key} room. "
                f"Surfaces edge bleeding at the room perimeter."
            ),
            params={
                "decorator": _variant, "shape": _shape_key,
                "tag": _DECORATOR_TAG_FOR_VARIANT[_variant],
            },
            build=(lambda s, v=_variant, k=_shape_key:
                   _decorator_result(v, k, seed=s)),
            seeds=(7,),
        ))


# ── Fixture matrix: well / fountain / tree / bush ──────────────────
#
# Fixtures are the per-tile stamp primitives that drop in
# walkable surface tiles. Each shape × fixture combination should
# render the fixture identically; the sample makes that visual.
# The fixture uses Tile.feature-driven emission, so we stamp a
# feature on the room's centre tile.


def _fixture_result(
    feature: str, shape_key: str, *, seed: int,
) -> BuildResult:
    """Build a single-room level with the given fixture stamped at
    the room's centre tile."""
    shape, rect, canvas = _SHAPES[shape_key]()
    level = _single_room_level(
        shape, rect=rect, canvas=canvas, theme="dungeon",
    )
    cx, cy = rect.center
    if level.in_bounds(cx, cy):
        level.tiles[cy][cx].feature = feature
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


_FIXTURE_FEATURES = {
    "well":            "well",
    "well_square":     "well_square",
    "fountain":        "fountain",
    "fountain_square": "fountain_square",
    "fountain_cross":  "fountain_cross",
    "tree":            "tree",
    "bush":            "bush",
}

for _fixture, _feature in _FIXTURE_FEATURES.items():
    for _shape_key in ("rect", "octagon", "circle"):
        CATALOG.append(SampleSpec(
            name=f"on_{_shape_key}",
            category=f"synthetic/fixtures/{_fixture}",
            description=(
                f"{_fixture} fixture stamped at the centre of a "
                f"{_shape_key} room."
            ),
            params={
                "fixture": _fixture, "feature": _feature,
                "shape": _shape_key,
            },
            build=(lambda s, f=_feature, k=_shape_key:
                   _fixture_result(f, k, seed=s)),
            seeds=(7,),
        ))


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
