"""Phase 7 backstop: cross-floor-kind portability tests.

After the rendering refactor, the per-tile decorators and the
terrain palette are floor-kind-agnostic. These tests construct
minimal synthetic levels of each floor kind and assert that the
matching IR op gets emitted regardless of the surrounding context.

The Rust SvgPainter no longer emits the legacy Python emitter's
``class="..."`` markers, so portability is now checked at the IR
layer (op-count snapshot) rather than the SVG-string layer. The
contract stays the same: drop a tile feature into any floor kind
and its decorator op fires.
"""

from __future__ import annotations

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    Level, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering.ir.structural import compute_structural
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.svg import render_floor_svg


def _floor_grid(w: int, h: int) -> Level:
    """Build a wall-bordered FLOOR grid with one Room covering the
    interior. Sufficient for ``build_floor_ir`` to produce a
    dungeon-poly clip."""
    level = Level.create_empty("L", "L", 1, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, w, h))]
    return level


def _op_counts(level: Level, *, seed: int = 0) -> dict[str, int]:
    """Return the IR ``op_counts`` dict for ``level``."""
    buf = bytes(build_floor_ir(level, seed=seed))
    return compute_structural(buf)["op_counts"]


# ── Trees on every floor kind ─────────────────────────────────


class TestTreePortability:
    def test_tree_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].feature = "tree"
        assert _op_counts(level).get("TreeFeatureOp", 0) >= 1

    def test_tree_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].feature = "tree"
        assert _op_counts(level).get("TreeFeatureOp", 0) >= 1

    def test_tree_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3].feature = "tree"
        assert _op_counts(level).get("TreeFeatureOp", 0) >= 1

    def test_tree_paints_on_cave(self) -> None:
        level = _floor_grid(6, 6)
        level.rooms = [Room(
            id="cave1",
            rect=Rect(0, 0, 6, 6),
            shape=CaveShape(tiles={
                (x, y) for y in range(6) for x in range(6)
            }),
        )]
        level.tiles[3][3].feature = "tree"
        assert _op_counts(level, seed=11).get("TreeFeatureOp", 0) >= 1


# ── Bushes on every floor kind ────────────────────────────────


class TestBushPortability:
    def test_bush_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].feature = "bush"
        assert _op_counts(level).get("BushFeatureOp", 0) >= 1

    def test_bush_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].feature = "bush"
        assert _op_counts(level).get("BushFeatureOp", 0) >= 1

    def test_bush_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3].feature = "bush"
        assert _op_counts(level).get("BushFeatureOp", 0) >= 1

    def test_bush_paints_on_cave(self) -> None:
        level = _floor_grid(6, 6)
        level.rooms = [Room(
            id="cave1",
            rect=Rect(0, 0, 6, 6),
            shape=CaveShape(tiles={
                (x, y) for y in range(6) for x in range(6)
            }),
        )]
        level.tiles[3][3].feature = "bush"
        assert _op_counts(level, seed=11).get("BushFeatureOp", 0) >= 1


# ── Water on every floor kind ─────────────────────────────────


class TestWaterPortability:
    def test_water_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        assert _op_counts(level).get("TerrainDetailOp", 0) >= 1

    def test_water_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        assert _op_counts(level).get("TerrainDetailOp", 0) >= 1

    def test_water_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        assert _op_counts(level).get("TerrainDetailOp", 0) >= 1


# ── Cobblestone on every floor kind ──────────────────────────


class TestCobblestonePortability:
    _COBBLE = '#8A7A6A'  # canonical stroke colour

    def test_street_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level)
        assert self._COBBLE in svg

    def test_paved_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].surface_type = SurfaceType.PAVED
        svg = render_floor_svg(level)
        assert self._COBBLE in svg

    def test_street_paints_on_cave(self) -> None:
        level = _floor_grid(6, 6)
        level.rooms = [Room(
            id="cave1",
            rect=Rect(0, 0, 6, 6),
            shape=CaveShape(tiles={
                (x, y) for y in range(6) for x in range(6)
            }),
        )]
        level.tiles[3][3].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level, seed=11)
        assert self._COBBLE in svg


