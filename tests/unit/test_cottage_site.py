"""Cottage site assembler (milestone 5).

A tiny one-building forest-only site. Empty of entities in v1 --
a TODO flags the v2 populator hook (hermit / witch / squatter).
See design/biome_features.md §6.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites.cottage import assemble_cottage
from nhc.hexcrawl.model import Biome


# ---------------------------------------------------------------------------
# Structural shape
# ---------------------------------------------------------------------------


class TestCottageStructure:
    def test_assemble_cottage_returns_single_building(self) -> None:
        site = assemble_cottage(
            "c1", random.Random(0), biome=Biome.FOREST,
        )
        assert len(site.buildings) == 1
        assert site.enclosure is None
        assert site.kind == "cottage"

    def test_assemble_cottage_has_wood_interior_brick_walls(
        self,
    ) -> None:
        site = assemble_cottage(
            "c2", random.Random(0), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        # Matches the farm assembler's convention: brick shell
        # around a wood interior.
        assert b.wall_material == "brick"
        assert b.interior_floor == "wood"


# ---------------------------------------------------------------------------
# Surface stays empty (v2 hermit / witch populator lives indoors)
# ---------------------------------------------------------------------------


def test_assemble_cottage_surface_is_always_empty() -> None:
    """The surface (garden ring) carries no entities in any v2
    outcome -- hermits and witches live inside the cottage, not
    on the outdoor field. The abandoned roll simply leaves the
    indoor level empty as well. See test_cottage_populator for
    the per-outcome indoor assertions."""
    site = assemble_cottage(
        "c3", random.Random(0), biome=Biome.FOREST,
    )
    assert site.surface.entities == []


# ---------------------------------------------------------------------------
# Walkable surface + door
# ---------------------------------------------------------------------------


def test_assemble_cottage_has_walkable_surface_ring_around_building() -> None:
    """The surface level must include a ring of walkable tiles
    around the building so the door-crossing handler can land the
    player next to the entry door."""
    site = assemble_cottage(
        "c4", random.Random(0), biome=Biome.FOREST,
    )
    surface = site.surface
    # Phase 3a/3b: GARDEN + FIELD ride on Terrain.GRASS so
    # walkable tiles include both FLOOR and GRASS terrain.
    walkable = sum(
        1 for row in surface.tiles for t in row
        if t.terrain in (Terrain.FLOOR, Terrain.GRASS)
    )
    assert walkable > 0
    # GARDEN ring specifically, per the design doc.
    garden = sum(
        1 for row in surface.tiles
        for t in row if t.surface_type is SurfaceType.GARDEN
    )
    assert garden > 0


def test_assemble_cottage_has_perimeter_door() -> None:
    """The single building must carry exactly one perimeter door
    so the door-crossing path can register it for surface entry."""
    site = assemble_cottage(
        "c5", random.Random(0), biome=Biome.FOREST,
    )
    b = site.buildings[0]
    doors = [
        (x, y) for (x, y) in b.shared_perimeter()
        if b.ground.tiles[y][x].feature == "door_closed"
    ]
    assert len(doors) == 1
    # building_doors maps the outside neighbour of the door to the
    # building side; expect exactly one surface-door mapping.
    assert len(site.building_doors) == 1
