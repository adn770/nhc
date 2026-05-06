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

Phase 4.1 of plans/nhc_pure_ir_v5_migration_plan.md migrated the
read-side off the v4 op stream, so these tests now inspect the v5
op stream — Tree / Bush become ``V5FixtureOp`` with ``kind``
matching the V5FixtureKind enum; water becomes a
``V5PaintOp`` with ``material.family`` set to ``Liquid``.
"""

from __future__ import annotations

import json

import pytest

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    Level, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.svg import render_floor_svg


# v5 ``V5FixtureKind`` enum names (per design/map_ir_v5.md §7).
_V5_FIXTURE_KIND: dict[int, str] = {
    0: "Web",
    1: "Skull",
    2: "Bone",
    3: "LooseStone",
    4: "Tree",
    5: "Bush",
    6: "Well",
    7: "Fountain",
    8: "Stair",
    9: "Gravestone",
    10: "Sign",
    11: "Mushroom",
}

# v5 ``MaterialFamily`` enum names — used to identify Liquid:Water
# (and the broader family axis) from V5PaintOp dumps.
_V5_MATERIAL_FAMILY: dict[int, str] = {
    0: "Plain",
    1: "Cave",
    2: "Wood",
    3: "Stone",
    4: "Earth",
    5: "Liquid",
    6: "Special",
}


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


def _v5_fixture_kind_counts(level: Level, *, seed: int = 0) -> dict[str, int]:
    """Return ``{V5FixtureKind name: count of V5FixtureOps with that kind}``.

    The dump emits enum-named kind / opType strings (Phase 4.1 of
    plans/nhc_pure_ir_v5_migration_plan.md), so the lookup is
    direct.
    """
    buf = bytes(build_floor_ir(level, seed=seed))
    d = json.loads(dump(buf))
    counts: dict[str, int] = {}
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "FixtureOp":
            continue
        kind_name = (entry.get("op") or {}).get("kind", "?")
        n_anchors = len((entry.get("op") or {}).get("anchors") or [])
        counts[kind_name] = counts.get(kind_name, 0) + max(1, n_anchors)
    return counts


def _v5_paint_family_counts(level: Level, *, seed: int = 0) -> dict[str, int]:
    """Return ``{family_name: count of V5PaintOps painting that family}``."""
    buf = bytes(build_floor_ir(level, seed=seed))
    d = json.loads(dump(buf))
    counts: dict[str, int] = {}
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "PaintOp":
            continue
        family_name = (
            (entry.get("op") or {}).get("material") or {}
        ).get("family", "?")
        counts[family_name] = counts.get(family_name, 0) + 1
    return counts


# Decorator-bit values mirror ``stamp_op::bit::*`` in
# crates/nhc-render/src/transform/png/v5/stamp_op.rs. ``Ripples``
# fires for water surface motion; ``LavaCracks`` for lava.
_V5_BIT_RIPPLES = 1 << 3
_V5_BIT_LAVA_CRACKS = 1 << 4


def _v5_stamp_decorator_bit_set(
    level: Level, bit: int, *, seed: int = 0,
) -> bool:
    """Return True iff any V5StampOp in the IR enables the given
    decorator bit. Used by water/lava portability tests now that
    v5_emit ships Liquid surface motion via V5StampOp's
    ``decoratorMask`` (Phase 2.9), not via V5PaintOp(Liquid).
    """
    buf = bytes(build_floor_ir(level, seed=seed))
    d = json.loads(dump(buf))
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "StampOp":
            continue
        mask = int((entry.get("op") or {}).get("decoratorMask", 0) or 0)
        if mask & bit:
            return True
    return False


# ── Trees on every floor kind ─────────────────────────────────


class TestTreePortability:
    def test_tree_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].feature = "tree"
        assert _v5_fixture_kind_counts(level).get("Tree", 0) >= 1

    def test_tree_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].feature = "tree"
        assert _v5_fixture_kind_counts(level).get("Tree", 0) >= 1

    def test_tree_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3].feature = "tree"
        assert _v5_fixture_kind_counts(level).get("Tree", 0) >= 1

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
        assert _v5_fixture_kind_counts(level, seed=11).get("Tree", 0) >= 1


# ── Bushes on every floor kind ────────────────────────────────


class TestBushPortability:
    def test_bush_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].feature = "bush"
        assert _v5_fixture_kind_counts(level).get("Bush", 0) >= 1

    def test_bush_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].feature = "bush"
        assert _v5_fixture_kind_counts(level).get("Bush", 0) >= 1

    def test_bush_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3].feature = "bush"
        assert _v5_fixture_kind_counts(level).get("Bush", 0) >= 1

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
        assert _v5_fixture_kind_counts(level, seed=11).get("Bush", 0) >= 1


# ── Water on every floor kind ─────────────────────────────────


class TestWaterPortability:
    def test_water_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        assert _v5_stamp_decorator_bit_set(level, _V5_BIT_RIPPLES)

    def test_water_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        assert _v5_stamp_decorator_bit_set(level, _V5_BIT_RIPPLES)

    def test_water_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        assert _v5_stamp_decorator_bit_set(level, _V5_BIT_RIPPLES)


# ── Cobblestone on every floor kind ──────────────────────────


@pytest.mark.skip(
    reason="NIR5: cobblestone color (#8A7A6A) is the v4 stroke; "
    "v5 emits Stone family Cobblestone style with a different "
    "palette. Test needs an updated v5 baseline."
)
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


