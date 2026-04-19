"""Ruin site assembler (milestone 6).

Ruins are abandoned dungeon entrances: a single partial building
inside a broken fortification, no service NPCs, with a mandatory
3-floor descent declared on the building. See
``design/biome_features.md`` §6.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.dungeon.sites.ruin import (
    RUIN_BUILDING_COUNT_RANGE,
    RUIN_DESCENT_FLOORS,
    RUIN_DESCENT_TEMPLATE,
    RUIN_ENCLOSURE_KIND,
    assemble_ruin,
)
from nhc.hexcrawl.model import Biome


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


class TestRuinStructure:
    def test_assemble_ruin_returns_site_with_ruin_kind(self) -> None:
        site = assemble_ruin(
            "r1", random.Random(0), biome=Biome.FOREST,
        )
        assert site.kind == "ruin"

    def test_assemble_ruin_has_one_building(self) -> None:
        lo, hi = RUIN_BUILDING_COUNT_RANGE
        for seed in range(8):
            site = assemble_ruin(
                f"r_{seed}", random.Random(seed), biome=Biome.FOREST,
            )
            assert lo <= len(site.buildings) <= hi

    def test_assemble_ruin_has_fortification_enclosure_with_broken_gate(
        self,
    ) -> None:
        site = assemble_ruin(
            "r2", random.Random(0), biome=Biome.FOREST,
        )
        assert site.enclosure is not None
        assert site.enclosure.kind == RUIN_ENCLOSURE_KIND
        # Broken gate: the ruin still exposes a gate on the
        # enclosure so the player has a natural landing point,
        # but it's conceptually "broken" (structural details
        # live on the surface rendering in v2).
        assert len(site.enclosure.gates) >= 1

    def test_assemble_ruin_has_partial_walls_on_perimeter(
        self,
    ) -> None:
        """Reuses the mysterious-temple trick: 2-4 perimeter wall
        tiles are swapped back to VOID so the building reads as
        half-collapsed."""
        site = assemble_ruin(
            "r3", random.Random(1), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        ground = b.ground
        footprint = b.base_shape.floor_tiles(b.base_rect)
        perimeter: set[tuple[int, int]] = set()
        for (x, y) in footprint:
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in footprint:
                        continue
                    if not ground.in_bounds(nx, ny):
                        continue
                    perimeter.add((nx, ny))
        void_count = sum(
            1 for (x, y) in perimeter
            if ground.tiles[y][x].terrain is Terrain.VOID
        )
        assert 2 <= void_count <= 4


# ---------------------------------------------------------------------------
# Mandatory descent
# ---------------------------------------------------------------------------


class TestRuinDescent:
    def test_assemble_ruin_building_has_stairs_down_on_ground(
        self,
    ) -> None:
        site = assemble_ruin(
            "r4", random.Random(0), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        ground = b.ground
        found = any(
            ground.tiles[y][x].feature == "stairs_down"
            for y in range(ground.height)
            for x in range(ground.width)
        )
        assert found

    def test_assemble_ruin_descent_is_mandatory_and_3_floors(
        self,
    ) -> None:
        site = assemble_ruin(
            "r5", random.Random(0), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        assert b.descent is not None
        assert b.descent.depth == RUIN_DESCENT_FLOORS
        assert RUIN_DESCENT_FLOORS == 3

    def test_ruin_descent_template_is_procedural_ruin(self) -> None:
        site = assemble_ruin(
            "r6", random.Random(0), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        assert b.descent is not None
        assert b.descent.template == RUIN_DESCENT_TEMPLATE
        assert RUIN_DESCENT_TEMPLATE == "procedural:ruin"


# ---------------------------------------------------------------------------
# Biome-specific surface flavour
# ---------------------------------------------------------------------------


_RUIN_BIOMES = [
    Biome.FOREST, Biome.DEADLANDS, Biome.MARSH,
    Biome.SANDLANDS, Biome.ICELANDS,
]


@pytest.mark.parametrize("biome", _RUIN_BIOMES)
def test_ruin_surface_has_biome_appropriate_floor_tiles(
    biome: Biome,
) -> None:
    """Every ruin biome must produce a walkable surface; the ring
    style (GARDEN for forest, FIELD for marsh, bare for the rest)
    is a flavour choice but the surface must have walkable floor
    tiles regardless."""
    site = assemble_ruin(
        f"r_{biome.value}", random.Random(0), biome=biome,
    )
    walkable = sum(
        1 for row in site.surface.tiles
        for t in row if t.terrain is Terrain.FLOOR
    )
    assert walkable > 0
    # Forest ruins have a GARDEN ring; marsh ruins use FIELD; the
    # other three biomes use bare FLOOR.
    surface_types = {
        t.surface_type for row in site.surface.tiles
        for t in row if t.terrain is Terrain.FLOOR
    }
    if biome is Biome.FOREST:
        assert SurfaceType.GARDEN in surface_types
    elif biome is Biome.MARSH:
        assert SurfaceType.FIELD in surface_types


# ---------------------------------------------------------------------------
# Abandoned: no service NPCs
# ---------------------------------------------------------------------------


def test_ruin_has_no_service_npcs() -> None:
    """Ruins are abandoned -- no merchant, priest, or innkeeper."""
    site = assemble_ruin(
        "r_abandoned", random.Random(0), biome=Biome.FOREST,
    )
    service_ids = {"merchant", "priest", "innkeeper", "adventurer"}
    for b in site.buildings:
        for f in b.floors:
            for e in f.entities:
                assert e.entity_id not in service_ids, (
                    f"ruin {site.id} has {e.entity_id} "
                    f"(expected no service NPCs)"
                )
    for e in site.surface.entities:
        assert e.entity_id not in service_ids
