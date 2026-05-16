"""Temple site assembler (milestone 5).

One stone building, one priest, shared across four biomes.
Mountain / forest are the "expected" variants; sandlands and
icelands are "mysterious" -- same structural layout but with
a handful of perimeter wall tiles dropped back to VOID so the
building reads as weathered. See design/biome_features.md §6.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import OctagonShape, RectShape, SurfaceType, Terrain
from nhc.sites.temple import assemble_temple
from nhc.hexcrawl.model import Biome


# ---------------------------------------------------------------------------
# Shape selection per biome
# ---------------------------------------------------------------------------


class TestTempleShape:
    def test_assemble_temple_mountain_is_octagon_stone(self) -> None:
        site = assemble_temple(
            "t_mtn", random.Random(1), biome=Biome.MOUNTAIN,
        )
        assert len(site.buildings) == 1
        b = site.buildings[0]
        assert isinstance(b.base_shape, OctagonShape)
        assert b.wall_material == "stone"
        assert b.interior_floor == "stone"

    def test_assemble_temple_forest_is_rect_stone_with_garden_ring(
        self,
    ) -> None:
        site = assemble_temple(
            "t_for", random.Random(1), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        assert isinstance(b.base_shape, RectShape)
        assert b.wall_material == "stone"
        # Forest temples get a GARDEN ring on the surface.
        garden_count = sum(
            1 for row in site.surface.tiles
            for t in row if t.surface_type == SurfaceType.GARDEN
        )
        assert garden_count > 0


# ---------------------------------------------------------------------------
# Mysterious variants -- partial walls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("biome", [Biome.SANDLANDS, Biome.ICELANDS])
class TestMysteriousTemple:
    def test_has_partial_walls(self, biome: Biome) -> None:
        """2-4 perimeter wall tiles are dropped back to VOID so the
        building reads as half-collapsed."""
        site = assemble_temple(
            f"t_{biome.value}", random.Random(0), biome=biome,
        )
        b = site.buildings[0]
        ground = b.ground
        # Count the perimeter wall tiles that were supposed to be
        # walls (every neighbour of a footprint tile that isn't
        # itself a footprint tile). Some must be VOID.
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
        assert 2 <= void_count <= 4, (
            f"expected 2-4 dropped wall tiles, got {void_count}"
        )

    def test_mysterious_temple_still_has_priest(
        self, biome: Biome,
    ) -> None:
        """Mysterious variants are not abandoned -- a hermit priest
        still tends the forgotten shrine so the player has a
        reachable service NPC. Since v2 M15 this is specifically
        the ``hermit_priest`` factory with a reduced service list
        (see test_mysterious_temple_v2 for the services check)."""
        site = assemble_temple(
            f"t_{biome.value}_priest", random.Random(0),
            biome=biome,
        )
        b = site.buildings[0]
        ground = b.ground
        priests = [
            e for e in ground.entities
            if e.entity_id in ("priest", "hermit_priest")
        ]
        assert len(priests) == 1
        assert priests[0].entity_id == "hermit_priest"


# ---------------------------------------------------------------------------
# Priest placement (shared across every biome)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "biome",
    [Biome.MOUNTAIN, Biome.FOREST, Biome.SANDLANDS, Biome.ICELANDS],
)
def test_assemble_temple_places_priest_on_ground_floor(
    biome: Biome,
) -> None:
    site = assemble_temple(
        f"t_{biome.value}_pp", random.Random(0), biome=biome,
    )
    b = site.buildings[0]
    # Expected (mountain / forest) temples get the full-service
    # priest; mysterious (sandlands / icelands) temples get the
    # v2 M15 hermit_priest with the reduced service list.
    priests = [
        e for e in b.ground.entities
        if e.entity_id in ("priest", "hermit_priest")
    ]
    assert len(priests) == 1
    priest = priests[0]
    assert "temple_services" in priest.extra
    assert priest.extra["temple_services"]


# ---------------------------------------------------------------------------
# Site kind
# ---------------------------------------------------------------------------


def test_temple_site_kind_is_temple() -> None:
    site = assemble_temple(
        "t_k", random.Random(0), biome=Biome.FOREST,
    )
    assert site.kind == "temple"


# ---------------------------------------------------------------------------
# Paved courtyard ring + exterior flower ring
# ---------------------------------------------------------------------------


def _footprint(site):
    b = site.buildings[0]
    return set(b.base_shape.floor_tiles(b.base_rect))


def _cheby(xy, footprint):
    return min(
        max(abs(xy[0] - fx), abs(xy[1] - fy))
        for (fx, fy) in footprint
    )


class TestTempleGroundRings:
    @pytest.mark.parametrize(
        "biome",
        [Biome.FOREST, Biome.MOUNTAIN, Biome.SANDLANDS],
    )
    def test_flagstone_courtyard_hugs_the_shrine(self, biome):
        from nhc.sites.temple import TEMPLE_PAVED_RING_WIDTH

        site = assemble_temple("t_p", random.Random(2), biome=biome)
        s = site.surface
        fp = _footprint(site)
        paved = [
            (x, y)
            for y, row in enumerate(s.tiles)
            for x, t in enumerate(row)
            if t.surface_type == SurfaceType.FLAGSTONE
        ]
        assert paved, f"{biome}: no flagstone ring"
        # Every paved surface tile sits within the courtyard band.
        for xy in paved:
            assert 1 <= _cheby(xy, fp) <= TEMPLE_PAVED_RING_WIDTH, xy

    @pytest.mark.parametrize(
        "biome",
        [Biome.FOREST, Biome.MOUNTAIN, Biome.SANDLANDS],
    )
    def test_exterior_flower_ring_surrounds_the_courtyard(self, biome):
        from nhc.sites.temple import TEMPLE_PAVED_RING_WIDTH

        site = assemble_temple("t_f", random.Random(2), biome=biome)
        s = site.surface
        fp = _footprint(site)
        flowers = [
            (x, y)
            for y, row in enumerate(s.tiles)
            for x, t in enumerate(row)
            if t.feature == "flower"
        ]
        assert flowers, f"{biome}: no flower ring"
        # A continuous planted ring sits exactly one tile beyond
        # the paving (the low wild scatter adds a few stray
        # flowers farther out, so only assert the ring exists —
        # not that every flower is on it).
        ring = [
            xy for xy in flowers
            if _cheby(xy, fp) == TEMPLE_PAVED_RING_WIDTH + 1
        ]
        assert len(ring) >= 8, (biome, len(ring))
        for xy in ring:
            assert s.tiles[xy[1]][xy[0]].surface_type is SurfaceType.GARDEN

    def test_void_margin_preserved(self):
        site = assemble_temple("t_v", random.Random(4), biome=Biome.FOREST)
        s = site.surface
        for x in range(s.width):
            assert s.tiles[0][x].terrain is Terrain.VOID
            assert s.tiles[s.height - 1][x].terrain is Terrain.VOID
        for y in range(s.height):
            assert s.tiles[y][0].terrain is Terrain.VOID
            assert s.tiles[y][s.width - 1].terrain is Terrain.VOID


class TestTempleGrassScatter:
    def test_forest_grass_gets_sparse_trees_bushes_flowers(self):
        # Aggregate across seeds: each kind shows up, but the
        # density stays low (a scatter, not a thicket).
        seen: set[str] = set()
        for seed in range(12):
            site = assemble_temple(
                f"t_s{seed}", random.Random(seed), biome=Biome.FOREST,
            )
            s = site.surface
            scattered = 0
            grass = 0
            for row in s.tiles:
                for t in row:
                    if (t.terrain is Terrain.GRASS
                            and t.surface_type is SurfaceType.GARDEN):
                        grass += 1
                        if t.feature in ("tree", "bush"):
                            scattered += 1
                            seen.add(t.feature)
                        elif t.feature == "flower":
                            seen.add("flower")
            assert grass > 0
            # Low density — far under a fifth of the open grass.
            assert scattered < grass * 0.2, (seed, scattered, grass)
        assert {"tree", "bush", "flower"} <= seen

    def test_scatter_only_on_garden_grass(self):
        site = assemble_temple(
            "t_sg", random.Random(3), biome=Biome.FOREST,
        )
        s = site.surface
        for row in s.tiles:
            for t in row:
                if t.feature in ("tree", "bush"):
                    assert t.terrain is Terrain.GRASS
                    assert t.surface_type is SurfaceType.GARDEN

    def test_non_forest_temple_has_no_scattered_trees(self):
        # Mountain temple ground is bare FLOOR, not grass — only
        # the planted flower ring carries features.
        site = assemble_temple(
            "t_m", random.Random(3), biome=Biome.MOUNTAIN,
        )
        s = site.surface
        kinds = {
            t.feature for row in s.tiles for t in row
            if t.feature is not None
        }
        assert "tree" not in kinds
        assert "bush" not in kinds
        assert "flower" in kinds  # the exterior ring

    def test_scatter_is_deterministic_per_seed(self):
        a = assemble_temple("t_d", random.Random(9), biome=Biome.FOREST)
        b = assemble_temple("t_d", random.Random(9), biome=Biome.FOREST)
        fa = {
            (x, y): t.feature
            for y, row in enumerate(a.surface.tiles)
            for x, t in enumerate(row) if t.feature
        }
        fb = {
            (x, y): t.feature
            for y, row in enumerate(b.surface.tiles)
            for x, t in enumerate(row) if t.feature
        }
        assert fa == fb
