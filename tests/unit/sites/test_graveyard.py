"""Graveyard site assembler — undead family.

Stone-walled FIELD plaza with a single ``tomb_entrance`` centrepiece
and an undead garrison sized by tier. Replaces the retired
``generate_undead_site`` (M4e of sites-unification).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.graveyard import (
    UNDEAD_COUNT_BY_TIER,
    UNDEAD_POOL_BY_TIER,
    assemble_graveyard,
    pick_undead_population,
)


def _feature_tiles(surface, tag: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, t in enumerate(row) if t.feature == tag
    ]


class TestAssembleGraveyardBasics:
    def test_returns_a_site(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        assert isinstance(site, Site)
        assert site.kind == "graveyard"

    def test_has_no_buildings(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        assert site.buildings == []

    def test_has_no_enclosure(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        assert site.enclosure is None

    def test_fits_in_medium_tier_dims(self):
        med_w, med_h = SITE_TIER_DIMS[SiteTier.MEDIUM]
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.width == med_w
        assert site.surface.height == med_h


class TestGraveyardFeatureTile:
    def test_stamps_one_tomb_entrance_tile(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        tombs = _feature_tiles(site.surface, "tomb_entrance")
        assert len(tombs) == 1

    def test_feature_tile_is_walkable(self):
        site = assemble_graveyard(
            "g1", random.Random(2),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        tx, ty = _feature_tiles(site.surface, "tomb_entrance")[0]
        tile = site.surface.tile_at(tx, ty)
        assert tile is not None
        assert tile.terrain == Terrain.FLOOR


class TestGraveyardSurface:
    def test_surface_tagged_as_field(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        field_tiles = sum(
            1 for row in site.surface.tiles for t in row
            if t.surface_type == SurfaceType.FIELD
        )
        assert field_tiles > 0

    def test_perimeter_has_walls(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        surface = site.surface
        wall_count = sum(
            1 for y in range(surface.height)
            for x in range(surface.width)
            if (x in (0, surface.width - 1)
                or y in (0, surface.height - 1))
            and surface.tiles[y][x].terrain == Terrain.WALL
        )
        assert wall_count > 0

    def test_metadata_faction_is_undead(self):
        site = assemble_graveyard(
            "g1", random.Random(1),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.metadata.faction == "undead"


class TestGraveyardDeterminism:
    def test_same_seed_same_feature_tile(self):
        a = assemble_graveyard(
            "g", random.Random(99),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        b = assemble_graveyard(
            "g", random.Random(99),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        assert (
            _feature_tiles(a.surface, "tomb_entrance")
            == _feature_tiles(b.surface, "tomb_entrance")
        )


class TestPickUndeadPopulation:
    def test_count_matches_tier_table(self):
        for tier, expected in UNDEAD_COUNT_BY_TIER.items():
            site = assemble_graveyard(
                "g", random.Random(7),
                feature=HexFeatureType.GRAVEYARD,
                tier=tier,
            )
            placements = pick_undead_population(
                site.surface, random.Random(7), tier,
            )
            assert len(placements) == expected, (
                f"tier {tier} expected {expected} placements, "
                f"got {len(placements)}"
            )

    def test_creatures_drawn_from_tier_pool(self):
        site = assemble_graveyard(
            "g", random.Random(7),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        placements = pick_undead_population(
            site.surface, random.Random(7), SiteTier.MEDIUM,
        )
        pool = set(UNDEAD_POOL_BY_TIER[SiteTier.MEDIUM])
        for cid, _xy in placements:
            assert cid in pool, (
                f"creature {cid!r} outside MEDIUM pool {pool}"
            )

    def test_placements_land_on_floor(self):
        site = assemble_graveyard(
            "g", random.Random(11),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        placements = pick_undead_population(
            site.surface, random.Random(11), SiteTier.MEDIUM,
        )
        assert placements
        for _cid, (x, y) in placements:
            tile = site.surface.tile_at(x, y)
            assert tile is not None
            assert tile.terrain is Terrain.FLOOR

    def test_excludes_reserved_tiles(self):
        site = assemble_graveyard(
            "g", random.Random(13),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.LARGE,
        )
        tomb = _feature_tiles(site.surface, "tomb_entrance")[0]
        entry = (
            site.surface.width // 2, site.surface.height - 2,
        )
        reserved = {tomb, entry}
        placements = pick_undead_population(
            site.surface, random.Random(13), SiteTier.LARGE,
            exclude=reserved,
        )
        for _cid, xy in placements:
            assert xy not in reserved

    def test_same_rng_same_placements(self):
        site = assemble_graveyard(
            "g", random.Random(5),
            feature=HexFeatureType.GRAVEYARD,
            tier=SiteTier.MEDIUM,
        )
        a = pick_undead_population(
            site.surface, random.Random(5), SiteTier.MEDIUM,
        )
        b = pick_undead_population(
            site.surface, random.Random(5), SiteTier.MEDIUM,
        )
        assert a == b
