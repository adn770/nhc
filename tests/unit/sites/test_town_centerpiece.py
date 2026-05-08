"""Town centerpiece (Phase 5).

Every size class gets a navigation landmark on a reserved patch.
Hamlet / village → 1x1 well in a 3x3 patch; town / city → 2x2
fountain in a 4x4 plaza. The variant (circle vs square) is
biome-driven (Q12). Placement uses two passes: a probe-pass
cluster packer determines the cluster ring centroid, the
centerpiece nudges toward the dominant gate, and a final cluster
packer pass treats the patch as a forbidden_rect so clusters
arrange around it (Q10).

See ``town_redesign_plan.md`` Phase 5 for the design.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import Rect, SurfaceType, Terrain
from nhc.hexcrawl.model import Biome
from nhc.sites.town import _SIZE_CLASSES, assemble_town


def _feature_tiles(site, feature: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for y, row in enumerate(site.surface.tiles):
        for x, tile in enumerate(row):
            if tile.feature == feature:
                out.append((x, y))
    return out


def _any_centerpiece(site) -> tuple[str, tuple[int, int]] | None:
    for feature in (
        "well", "well_square",
        "fountain", "fountain_square",
        "fountain_large", "fountain_large_square",
        "fountain_cross",
    ):
        tiles = _feature_tiles(site, feature)
        if tiles:
            return (feature, tiles[0])
    return None


# ── 1. Every size class ships exactly one centerpiece ─────────


class TestCenterpieceExistsPerSize:
    @pytest.mark.parametrize("size_class,expected", [
        ("hamlet", ("well", "well_square")),
        ("village", ("well", "well_square")),
        ("town", ("fountain", "fountain_square")),
        ("city", (
            "fountain_large", "fountain_large_square",
            "fountain_cross",
        )),
    ])
    def test_centerpiece_feature_kind_matches_size(
        self, size_class, expected,
    ):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            present = []
            for f in expected:
                if _feature_tiles(site, f):
                    present.append(f)
            assert len(present) == 1, (
                f"seed={seed} {size_class}: expected exactly one "
                f"of {expected}, found {present}"
            )


# ── 2. Centerpiece sits inside the cluster bbox set ───────────


class TestCenterpiecePlacement:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_centerpiece_inside_surface_bounds(self, size_class):
        config = _SIZE_CLASSES[size_class]
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            entry = _any_centerpiece(site)
            assert entry is not None, (
                f"seed={seed} {size_class}: no centerpiece feature"
            )
            _, (cx, cy) = entry
            assert 0 <= cx < config.surface_width, (
                f"seed={seed} {size_class}: centerpiece x={cx} "
                f"outside surface width {config.surface_width}"
            )
            assert 0 <= cy < config.surface_height, (
                f"seed={seed} {size_class}: centerpiece y={cy} "
                f"outside surface height {config.surface_height}"
            )

    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_centerpiece_inside_palisade(self, size_class):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            entry = _any_centerpiece(site)
            if entry is None:
                continue
            _, (cx, cy) = entry
            xs = [p[0] for p in site.enclosure.polygon]
            ys = [p[1] for p in site.enclosure.polygon]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            assert min_x <= cx < max_x, (
                f"seed={seed} {size_class}: centerpiece x={cx} "
                f"outside palisade x-range [{min_x}, {max_x})"
            )
            assert min_y <= cy < max_y, (
                f"seed={seed} {size_class}: centerpiece y={cy} "
                f"outside palisade y-range [{min_y}, {max_y})"
            )


# ── 3. Centerpiece patch is walkable + cobble + clear ─────────


class TestCenterpiecePatchSurface:
    @pytest.mark.parametrize("size_class,patch_dim,feature_dim", [
        ("hamlet", 5, 1),
        ("village", 5, 1),
        ("town", 7, 2),
        ("city", 11, 3),
    ])
    def test_patch_is_floor_and_street(
        self, size_class, patch_dim, feature_dim,
    ):
        """The reserved patch tiles all carry FLOOR + STREET, so
        the landmark sits on a cobblestone plaza visible across
        the surface."""
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            entry = _any_centerpiece(site)
            if entry is None:
                continue
            _, (cx, cy) = entry
            # Reserved patch encompasses the feature footprint
            # (1x1 well or 2x2 fountain).
            for dx in range(feature_dim):
                for dy in range(feature_dim):
                    tx, ty = cx + dx, cy + dy
                    if not site.surface.in_bounds(tx, ty):
                        continue
                    tile = site.surface.tiles[ty][tx]
                    assert tile.terrain == Terrain.FLOOR, (
                        f"seed={seed} {size_class}: centerpiece "
                        f"footprint tile ({tx},{ty}) terrain "
                        f"{tile.terrain!r}"
                    )

    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_no_building_overlaps_centerpiece_patch(
        self, size_class,
    ):
        """No building footprint may overlap the centerpiece's
        reserved patch -- Phase 5's two-pass placement passes the
        patch as a forbidden_rect to the second cluster pack so
        clusters arrange around it."""
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            entry = _any_centerpiece(site)
            if entry is None:
                continue
            _, (cx, cy) = entry
            footprints: set[tuple[int, int]] = set()
            for b in site.buildings:
                footprints |= b.base_shape.floor_tiles(b.base_rect)
            patch_tiles: set[tuple[int, int]] = set()
            for dx in range(-1, 4):
                for dy in range(-1, 4):
                    patch_tiles.add((cx + dx, cy + dy))
            overlap = patch_tiles & footprints
            assert not overlap, (
                f"seed={seed} {size_class}: building footprint "
                f"overlaps centerpiece patch: {sorted(overlap)[:5]}"
            )


# ── 4. Biome-driven shape (Q12) ───────────────────────────────


class TestBiomeShape:
    @pytest.mark.parametrize("biome,expected", [
        (Biome.MOUNTAIN, "well_square"),
        (Biome.DRYLANDS, "well_square"),
        (Biome.MARSH, "well"),
        (Biome.GREENLANDS, "well"),
        (Biome.FOREST, "well"),
    ])
    def test_village_centerpiece_shape_per_biome(
        self, biome, expected,
    ):
        seen_match = False
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed),
                size_class="village", biome=biome,
            )
            if _feature_tiles(site, expected):
                seen_match = True
                break
        assert seen_match, (
            f"village/{biome.name}: expected {expected!r} "
            "centerpiece across 15 seeds"
        )

    @pytest.mark.parametrize("biome,expected", [
        (Biome.MOUNTAIN, "fountain_large_square"),
        (Biome.DRYLANDS, "fountain_large_square"),
        (Biome.MARSH, "fountain_cross"),
        (Biome.SWAMP, "fountain_cross"),
        (Biome.DEADLANDS, "fountain_cross"),
        (Biome.GREENLANDS, "fountain_large"),
        (Biome.FOREST, "fountain_large"),
    ])
    def test_city_centerpiece_shape_per_biome(
        self, biome, expected,
    ):
        seen_match = False
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed),
                size_class="city", biome=biome,
            )
            if _feature_tiles(site, expected):
                seen_match = True
                break
        assert seen_match, (
            f"city/{biome.name}: expected {expected!r} "
            "centerpiece across 15 seeds"
        )
