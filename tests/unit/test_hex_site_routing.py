"""Tests for hex-feature -> site-kind routing.

After M15 the building generator produces Site instances. The
hex-feature placement code must set DungeonRef.site_kind so the
game layer can later dispatch through assemble_site().
"""

from __future__ import annotations

from nhc.hexcrawl._features import _site_kind_for
from nhc.hexcrawl.model import HexFeatureType


class TestSiteKindForFeature:
    def test_tower_maps_to_tower(self):
        assert _site_kind_for(HexFeatureType.TOWER) == "tower"

    def test_keep_maps_to_keep(self):
        assert _site_kind_for(HexFeatureType.KEEP) == "keep"

    def test_mansion_maps_to_mansion(self):
        assert _site_kind_for(HexFeatureType.MANSION) == "mansion"

    def test_farm_maps_to_farm(self):
        assert _site_kind_for(HexFeatureType.FARM) == "farm"

    def test_city_and_village_map_to_town(self):
        assert _site_kind_for(HexFeatureType.CITY) == "town"
        assert _site_kind_for(HexFeatureType.VILLAGE) == "town"

    def test_cave_has_no_site_kind(self):
        """Traditional dungeons return None -- they still flow
        through the template-based pipeline."""
        assert _site_kind_for(HexFeatureType.CAVE) is None

    def test_ruin_routes_to_ruin_site(self):
        """After biome-features M1, ruin hexes dispatch through
        the ruin site assembler (see design/biome_features.md §6)."""
        assert _site_kind_for(HexFeatureType.RUIN) == "ruin"

    def test_graveyard_has_no_site_kind(self):
        assert _site_kind_for(HexFeatureType.GRAVEYARD) is None
