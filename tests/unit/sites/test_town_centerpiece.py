"""Town plazas (BSP-neighbourhood redesign, D7).

Every settlement reserves one or more plazas, stamped by tier:
- hamlet  -> 1 small well-square
- village -> 1 big fountain square (B3: re-tiered from a well)
- town    -> 1 big fountain + 1 small well
- city    -> 1 big large-fountain + 2 small wells

The feature variant (circle / square / cross) is biome-driven, and no
building footprint may overlap a plaza feature. See
design/town_generator.md §3.2.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType
from nhc.hexcrawl.model import Biome
from nhc.sites.town import _SIZE_CLASSES, assemble_town

_WELL = ("well", "well_square")
_FOUNTAIN = ("fountain", "fountain_square")
_FOUNTAIN_LARGE = (
    "fountain_large", "fountain_large_square", "fountain_cross",
)


def _feature_tiles(site, feature: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for x, y, tile in site.surface.iter_world()
        if tile.feature == feature
    ]


def _count_family(site, family: tuple[str, ...]) -> int:
    return sum(len(_feature_tiles(site, f)) for f in family)


# ── 1. Each size class reserves its plaza tiers ───────────────


class TestPlazaCountsPerSize:
    @pytest.mark.parametrize("size_class,big,small", [
        ("hamlet", 0, 1),
        ("village", 1, 0),
        ("town", 1, 1),
        ("city", 1, 2),
    ])
    def test_plaza_tier_counts(self, size_class, big, small):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            big_count = (
                _count_family(site, _FOUNTAIN_LARGE)
                if size_class == "city"
                else _count_family(site, _FOUNTAIN)
            )
            assert big_count == big, (
                f"seed={seed} {size_class}: big plazas {big_count} != {big}"
            )
            assert _count_family(site, _WELL) == small, (
                f"seed={seed} {size_class}: small plazas != {small}"
            )


# ── 2. Plaza features sit inside the surface / palisade ───────


class TestPlazaPlacement:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_features_inside_surface_bounds(self, size_class):
        config = _SIZE_CLASSES[size_class]
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            for fam in (_WELL, _FOUNTAIN, _FOUNTAIN_LARGE):
                for f in fam:
                    for cx, cy in _feature_tiles(site, f):
                        assert 0 <= cx < config.surface_width
                        assert 0 <= cy < config.surface_height

    @pytest.mark.parametrize("size_class", ["village", "town", "city"])
    def test_features_inside_palisade(self, size_class):
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            xs = [p[0] for p in site.enclosure.polygon]
            ys = [p[1] for p in site.enclosure.polygon]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            for fam in (_WELL, _FOUNTAIN, _FOUNTAIN_LARGE):
                for f in fam:
                    for cx, cy in _feature_tiles(site, f):
                        assert min_x <= cx < max_x
                        assert min_y <= cy < max_y


# ── 3. Plaza surface + no building overlap ────────────────────


class TestPlazaSurface:
    def test_big_plaza_feature_on_street(self):
        # Big plaza is a full cobblestone square.
        for size_class in ("village", "town", "city"):
            for seed in range(10):
                site = assemble_town(
                    "t1", random.Random(seed), size_class=size_class,
                )
                fam = (
                    _FOUNTAIN_LARGE if size_class == "city" else _FOUNTAIN
                )
                for f in fam:
                    for cx, cy in _feature_tiles(site, f):
                        tile = site.surface.tile_at(cx, cy)
                        assert tile.surface_type is SurfaceType.STREET

    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_no_building_on_plaza_feature(self, size_class):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            footprints: set[tuple[int, int]] = set()
            for b in site.buildings:
                footprints |= b.base_shape.floor_tiles(b.base_rect)
            for fam in (_WELL, _FOUNTAIN, _FOUNTAIN_LARGE):
                for f in fam:
                    for tile in _feature_tiles(site, f):
                        assert tile not in footprints


# ── 4. Biome-driven feature variant ──────────────────────────


class TestBiomeShape:
    @pytest.mark.parametrize("biome,expected", [
        (Biome.MOUNTAIN, "fountain_square"),
        (Biome.DRYLANDS, "fountain_square"),
        (Biome.GREENLANDS, "fountain"),
        (Biome.FOREST, "fountain"),
    ])
    def test_village_big_plaza_shape_per_biome(self, biome, expected):
        # B3: villages now carry a fountain, not a well.
        seen = False
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed),
                size_class="village", biome=biome,
            )
            if _feature_tiles(site, expected):
                seen = True
                break
        assert seen, f"village/{biome.name}: expected {expected!r}"

    @pytest.mark.parametrize("biome,expected", [
        (Biome.MOUNTAIN, "fountain_large_square"),
        (Biome.DRYLANDS, "fountain_large_square"),
        (Biome.MARSH, "fountain_cross"),
        (Biome.SWAMP, "fountain_cross"),
        (Biome.DEADLANDS, "fountain_cross"),
        (Biome.GREENLANDS, "fountain_large"),
        (Biome.FOREST, "fountain_large"),
    ])
    def test_city_big_plaza_shape_per_biome(self, biome, expected):
        seen = False
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed),
                size_class="city", biome=biome,
            )
            if _feature_tiles(site, expected):
                seen = True
                break
        assert seen, f"city/{biome.name}: expected {expected!r}"

    # Note: MOUNTAIN suppresses the palisade -> single-plot -> no small
    # plazas (Q2), so a square-variant well is tested via DRYLANDS, which
    # keeps its palisade.
    @pytest.mark.parametrize("biome,expected", [
        (Biome.DRYLANDS, "well_square"),
        (Biome.GREENLANDS, "well"),
        (Biome.FOREST, "well"),
    ])
    def test_city_small_plaza_well_shape_per_biome(self, biome, expected):
        seen = False
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed),
                size_class="city", biome=biome,
            )
            if _feature_tiles(site, expected):
                seen = True
                break
        assert seen, f"city small/{biome.name}: expected {expected!r}"
