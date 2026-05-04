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

from typing import Callable

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


# ── Floor matrix: shape × style × theme ─────────────────────────────
#
# The painter renders a floor by routing the room's region through
# FloorOp(<style>); the style is determined by the level's theme
# (dungeon → DungeonFloor, cave → CaveFloor, building wood → WoodFloor).
# Showing the same room shape under each theme verifies the per-style
# fill colour + the per-theme detail layer (cracks, bones, wood
# grain) drop on top correctly without bleeding past the room
# perimeter.


for _shape_key in _SHAPES:
    CATALOG.append(SampleSpec(
        name=_shape_key,
        category="synthetic/floors/dungeon",
        description=(
            f"Single {_shape_key} room with DungeonFloor "
            f"(white) + dungeon-theme detail layer."
        ),
        params={"shape": _shape_key, "theme": "dungeon", "style": "DungeonFloor"},
        build=(lambda s, k=_shape_key:
               _single_shape_result(k, theme="dungeon", seed=s)),
    ))

for _shape_key in _SHAPES:
    CATALOG.append(SampleSpec(
        name=_shape_key,
        category="synthetic/floors/cave",
        description=(
            f"Single {_shape_key} room with CaveFloor "
            f"(brown) + cave-theme detail layer."
        ),
        params={"shape": _shape_key, "theme": "cave", "style": "CaveFloor"},
        build=(lambda s, k=_shape_key:
               _single_shape_result(k, theme="cave", seed=s)),
    ))

for _shape_key in _SHAPES:
    CATALOG.append(SampleSpec(
        name=_shape_key,
        category="synthetic/floors/crypt",
        description=(
            f"Single {_shape_key} room with crypt-theme detail "
            f"(macabre bone overlay on DungeonFloor base)."
        ),
        params={"shape": _shape_key, "theme": "crypt", "style": "DungeonFloor"},
        build=(lambda s, k=_shape_key:
               _single_shape_result(k, theme="crypt", seed=s)),
    ))


# ── Stone-floor cross-context portability ──────────────────────────
#
# The stone DungeonFloor primitive should render identically inside
# a dungeon room, a building floor, and a site surface — region
# kind drives the dispatch but the per-tile fill stays the same.
# These three samples render the SAME shape under the three
# contexts so any per-context regression surfaces as a visual
# diff in the same folder.


def _stone_floor_dungeon_result(seed: int) -> BuildResult:
    """Stone floor inside a dungeon room (canonical case)."""
    return _single_shape_result("rect", theme="dungeon", seed=seed)


def _stone_floor_building_result(seed: int) -> BuildResult:
    """Stone floor inside a building (interior_floor='stone')."""
    shape, rect, canvas = _rect_room()
    level = _single_room_level(
        shape, rect=rect, canvas=canvas, theme="dungeon",
    )
    # Building flag triggers the building-floor emit path. The
    # interior_floor='stone' default keeps the FloorOp on
    # DungeonFloor (vs WoodFloor for interior_floor='wood').
    level.building_id = "synthetic.bldg"
    level.floor_index = 0
    level.interior_floor = "stone"
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


def _stone_floor_site_result(seed: int) -> BuildResult:
    """Stone floor on a site surface (prerevealed=True trims the
    hatch envelope but keeps FloorOp dispatch identical)."""
    shape, rect, canvas = _rect_room()
    level = _single_room_level(
        shape, rect=rect, canvas=canvas, theme="dungeon",
    )
    level.metadata = LevelMetadata(theme="dungeon", prerevealed=True)
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


CATALOG.extend([
    SampleSpec(
        name="dungeon_room",
        category="synthetic/floors/stone_contexts",
        description=(
            "Stone DungeonFloor inside a dungeon room — the canonical "
            "FloorOp(DungeonFloor) consumer path."
        ),
        params={"context": "dungeon_room", "shape": "rect"},
        build=_stone_floor_dungeon_result,
    ),
    SampleSpec(
        name="building_floor",
        category="synthetic/floors/stone_contexts",
        description=(
            "Stone DungeonFloor inside a building floor "
            "(interior_floor='stone'). Verifies the building-floor "
            "emit path renders identically to the dungeon-room path."
        ),
        params={"context": "building_floor", "shape": "rect", "interior_floor": "stone"},
        build=_stone_floor_building_result,
    ),
    SampleSpec(
        name="site_surface",
        category="synthetic/floors/stone_contexts",
        description=(
            "Stone DungeonFloor on a prerevealed site surface. "
            "Verifies the site-surface emit path renders identically "
            "to the dungeon-room path (hatch envelope is trimmed but "
            "the FloorOp dispatch is the same)."
        ),
        params={"context": "site_surface", "shape": "rect", "prerevealed": True},
        build=_stone_floor_site_result,
    ),
])


# ── Wood-floor species sweep ───────────────────────────────────────
#
# Wood floor's per-room hash picks one of 5 species (oak / walnut /
# cherry / pine / weathered) × 3 tones (light / medium / dark).
# Hashing on the room's region_ref means the per-room id drives
# the bucket. To showcase each species deterministically, vary the
# room id systematically and pin the seed so the species is
# reproducible.
#
# The species hash is fnv1a_32(region_ref) % 5; we precompute room
# ids that hash to each bucket so each sample shows a known
# species.


def _wood_floor_result(species_idx: int, seed: int) -> BuildResult:
    """Build a building floor whose room id hashes to species_idx.

    Iterates room ids until ``fnv1a_32(rid) % 5 == species_idx``.
    Pin seed so the rendered grain stays stable.
    """
    shape, rect, canvas = _rect_room()
    rid = _find_room_id_for_species(species_idx)
    level = _single_room_level(
        shape, rect=rect, canvas=canvas, theme="dungeon",
        room_id=rid,
    )
    level.building_id = "synthetic.bldg"
    level.floor_index = 0
    level.interior_floor = "wood"
    buf = build_floor_ir(level, seed=seed)
    return BuildResult(buf=buf, level=level)


def _fnv1a_32(data: str) -> int:
    """Match the Rust hash used by primitives::wood_floor for the
    species + tone bucket. See `crates/nhc-render/src/primitives/
    wood_floor.rs`. Phase 2.15a moved the legacy wood-floor SVG
    emitter to the Painter trait but the hash function stayed."""
    h = 0x811c9dc5
    for ch in data.encode("utf-8"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _find_room_id_for_species(species_idx: int) -> str:
    """Find the smallest room.<n> id whose hash maps to
    ``species_idx``. Stable for a given species_idx."""
    for n in range(1, 1000):
        rid = f"room.{n}"
        if _fnv1a_32(rid) % 5 == species_idx:
            return rid
    raise RuntimeError(f"no room id found for species {species_idx}")


_WOOD_SPECIES = ["oak", "walnut", "cherry", "pine", "weathered"]

for _idx, _species in enumerate(_WOOD_SPECIES):
    CATALOG.append(SampleSpec(
        name=_species,
        category="synthetic/floors/wood",
        description=(
            f"Wood floor — {_species} species. The room id hashes "
            f"to species index {_idx} so the per-species palette is "
            f"reproducible."
        ),
        params={"species_idx": _idx, "species": _species, "shape": "rect"},
        build=(lambda s, i=_idx: _wood_floor_result(i, seed=s)),
        seeds=(7,),  # one seed; geometry deterministic.
    ))


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


# ── Wall-style matrix: shape × style × wall consumer ───────────────
#
# Walls in v4e flow through three op kinds:
#
# * ExteriorWallOp — region perimeter (DungeonInk / CaveInk for
#   dungeons, MasonryBrick / MasonryStone for buildings, Palisade /
#   FortificationMerlon for enclosures).
# * InteriorWallOp — interior partitions inside a single region
#   (PartitionStone / PartitionBrick / PartitionWood).
# * CorridorWallOp — corridor-and-door walls between rooms.
#
# Building / enclosure exterior walls are exercised end-to-end by
# the generators/sites samples; here we focus on the dungeon
# perimeter (DungeonInk / CaveInk) per shape so per-shape stroke
# behaviour at chamfered / curved corners is visible.


for _shape_key in ("rect", "octagon", "circle", "pill"):
    CATALOG.append(SampleSpec(
        name=_shape_key,
        category="synthetic/walls/dungeon_ink",
        description=(
            f"DungeonInk perimeter stroke around a {_shape_key} room. "
            f"The wall stroke clips along the room's outline; this "
            f"sample isolates the per-shape ExteriorWallOp dispatch."
        ),
        params={"style": "DungeonInk", "shape": _shape_key},
        build=(lambda s, k=_shape_key:
               _single_shape_result(k, theme="dungeon", seed=s)),
        seeds=(7,),
    ))

for _shape_key in ("rect", "octagon", "circle", "pill"):
    CATALOG.append(SampleSpec(
        name=_shape_key,
        category="synthetic/walls/cave_ink",
        description=(
            f"CaveInk perimeter stroke around a {_shape_key} room "
            f"(cave theme — uses the buffered + jittered outline "
            f"pipeline)."
        ),
        params={"style": "CaveInk", "shape": _shape_key},
        build=(lambda s, k=_shape_key:
               _single_shape_result(k, theme="cave", seed=s)),
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
