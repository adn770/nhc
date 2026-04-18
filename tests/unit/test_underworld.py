"""Tests for the underworld region system."""

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.underworld import (
    UnderworldRegion,
    build_regions,
    floor_dimensions,
    max_depth_for_cluster,
    theme_for_underworld_depth,
)


class TestMaxDepthForCluster:
    def test_single_cave(self):
        assert max_depth_for_cluster(1) == 2

    def test_small_complex(self):
        assert max_depth_for_cluster(2) == 3
        assert max_depth_for_cluster(3) == 3

    def test_underworld(self):
        assert max_depth_for_cluster(4) == 4
        assert max_depth_for_cluster(6) == 4

    def test_moria_scale(self):
        assert max_depth_for_cluster(7) == 5
        assert max_depth_for_cluster(10) == 5


class TestThemeForUnderworldDepth:
    def test_shallow_is_cave(self):
        assert theme_for_underworld_depth(1) == "cave"
        assert theme_for_underworld_depth(2) == "cave"

    def test_depth_3_is_fungal(self):
        assert theme_for_underworld_depth(3) == "fungal_cavern"

    def test_depth_4_is_lava(self):
        assert theme_for_underworld_depth(4) == "lava_chamber"

    def test_depth_5_is_lake(self):
        assert theme_for_underworld_depth(5) == "underground_lake"


class TestFloorDimensions:
    def test_solo_cave_floor2(self):
        w, h = floor_dimensions(1, 2)
        assert w == 50 + 15 + 10  # 75
        assert h == 30 + 10 + 5   # 45

    def test_larger_cluster_deeper(self):
        w1, h1 = floor_dimensions(4, 2)
        w2, h2 = floor_dimensions(4, 4)
        assert w2 > w1
        assert h2 > h1

    def test_more_members_wider(self):
        w1, _ = floor_dimensions(2, 2)
        w2, _ = floor_dimensions(5, 2)
        assert w2 > w1


class TestBuildRegions:
    def test_builds_from_clusters(self):
        clusters = {
            HexCoord(0, 0): [HexCoord(0, 0), HexCoord(1, 0)],
            HexCoord(5, 5): [HexCoord(5, 5)],
        }
        regions = build_regions(clusters)
        assert len(regions) == 2
        assert HexCoord(0, 0) in regions
        assert HexCoord(5, 5) in regions

    def test_region_depth_from_size(self):
        clusters = {
            HexCoord(0, 0): [HexCoord(0, 0), HexCoord(1, 0),
                             HexCoord(0, 1)],
        }
        regions = build_regions(clusters)
        r = regions[HexCoord(0, 0)]
        assert r.max_depth == 3  # 3 caves → Cave Complex

    def test_region_fields(self):
        clusters = {
            HexCoord(2, 3): [HexCoord(2, 3)],
        }
        regions = build_regions(clusters)
        r = regions[HexCoord(2, 3)]
        assert r.canonical_coord == HexCoord(2, 3)
        assert r.member_coords == [HexCoord(2, 3)]
        assert r.max_depth == 2
        assert r.biome == "cave"

    def test_moria_scale_region(self):
        members = [HexCoord(i, 0) for i in range(8)]
        clusters = {HexCoord(0, 0): members}
        regions = build_regions(clusters)
        assert regions[HexCoord(0, 0)].max_depth == 5
