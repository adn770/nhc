"""Stone surface regions must carve interior holes.

Regression for the "garden patch renders on pavement" bug: a paved
courtyard that encloses a GARDEN island used to emit its stone region
as an exterior-ring-only polygon (``_terrain_cluster_coords`` dropped
``merged.interiors``). The solid fill then painted over the enclosed
grass, so trees / bushes / flowers on the garden island rendered
sitting on bare stone instead of a green grass patch.

Every stone surface region (pavement / paved / brick / flagstone /
opus_romano) that fully encloses a non-matching tile must carve that
tile out as a hole so the grass painted underneath shows through.
"""

from __future__ import annotations

import json

import pytest

from nhc.dungeon.model import (
    Level, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir


# (surface_type stamped on the courtyard, region id prefix it maps to)
_STONE_SURFACES = [
    (SurfaceType.PAVEMENT, "pavement"),
    (SurfaceType.PAVED, "paved"),
    (SurfaceType.BRICK, "brick"),
    (SurfaceType.FLAGSTONE, "flagstone"),
    (SurfaceType.OPUS_ROMANO, "opus_romano"),
]


def _courtyard_with_garden_island(surface: SurfaceType) -> Level:
    """7x7 stone courtyard (terrain GRASS) with a 1-tile GARDEN island
    at the centre — the stone region encloses the garden as a hole."""
    level = Level.create_empty("L", "L", 1, 7, 7)
    for x, y, _tile in level.iter_world():
        level.set_tile(
            x, y, Tile(terrain=Terrain.GRASS, surface_type=surface),
        )
    level.set_tile(
        3, 3, Tile(terrain=Terrain.GRASS, surface_type=SurfaceType.GARDEN),
    )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 7, 7))]
    return level


def _region_outline(level: Level, prefix: str) -> dict:
    buf = bytes(build_floor_ir(level, seed=0))
    d = json.loads(dump(buf))
    for region in d.get("regions", []):
        rid = str(region.get("id", ""))
        if rid.startswith(f"{prefix}."):
            return region.get("outline") or {}
    raise AssertionError(f"no region with prefix {prefix!r} emitted")


def _ring_is_hole(ring: dict) -> bool:
    return bool(ring.get("isHole", ring.get("is_hole", False)))


@pytest.mark.parametrize("surface,prefix", _STONE_SURFACES)
def test_stone_region_carves_enclosed_garden_hole(
    surface: SurfaceType, prefix: str,
) -> None:
    """A stone courtyard enclosing a GARDEN island emits a multi-ring
    outline with an interior hole, so the grass shows through."""
    outline = _region_outline(_courtyard_with_garden_island(surface), prefix)
    rings = outline.get("rings") or []
    assert len(rings) >= 2, (
        f"{prefix}: expected exterior + hole ring, got {len(rings)} "
        f"(enclosed garden island not carved out)"
    )
    assert any(_ring_is_hole(r) for r in rings), (
        f"{prefix}: no interior hole ring — garden island filled over"
    )
