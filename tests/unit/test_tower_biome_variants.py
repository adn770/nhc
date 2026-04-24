"""Forest watchtower and mountain tower gameplay variants
(M14 of biome-features v2).

v1 shipped slot 54 (forest watchtower) and slot 76 (mountain
tower) as tile-only identity: same assembler, same floor count
range, same shape pool. v2 backs those visuals with gameplay
differentiation: the forest watchtower is capped at two floors
and carries a wood roof, while the mountain tower is stone-only
on every floor. Every other biome keeps v1 behaviour.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites._site import assemble_site
from nhc.sites.tower import (
    TOWER_FLOOR_COUNT_RANGE, assemble_tower,
)
from nhc.hexcrawl.model import Biome


SEEDS = range(20)


class TestForestTowerVariant:
    def test_forest_tower_caps_at_two_floors(self):
        for seed in SEEDS:
            site = assemble_tower(
                f"ft{seed}", random.Random(seed),
                biome=Biome.FOREST,
            )
            b = site.buildings[0]
            assert len(b.floors) <= 2, (
                f"seed={seed}: forest tower has {len(b.floors)} "
                f"floors; expected <= 2"
            )
            assert len(b.floors) >= 1

    def test_forest_tower_has_wood_roof(self):
        for seed in SEEDS:
            site = assemble_tower(
                f"ft{seed}", random.Random(seed),
                biome=Biome.FOREST,
            )
            b = site.buildings[0]
            assert getattr(b, "roof_material", None) == "wood", (
                f"seed={seed}: expected wood roof on forest "
                f"tower, got {getattr(b, 'roof_material', None)!r}"
            )


class TestMountainTowerVariant:
    def test_mountain_tower_is_stone_on_every_floor(self):
        for seed in SEEDS:
            site = assemble_tower(
                f"mt{seed}", random.Random(seed),
                biome=Biome.MOUNTAIN,
            )
            b = site.buildings[0]
            assert b.wall_material == "stone"
            assert b.interior_floor == "stone"
            for f in b.floors:
                assert f.interior_floor == "stone", (
                    f"seed={seed} floor {f.id}: "
                    f"interior_floor={f.interior_floor!r}"
                )

    def test_mountain_tower_floor_count_unchanged_from_default(self):
        """Mountain towers inherit the default floor-count range,
        unlike forest watchtowers which clamp to 2."""
        lo, hi = TOWER_FLOOR_COUNT_RANGE
        for seed in SEEDS:
            site = assemble_tower(
                f"mt{seed}", random.Random(seed),
                biome=Biome.MOUNTAIN,
            )
            n = len(site.buildings[0].floors)
            assert lo <= n <= hi


class TestDefaultsPreserved:
    def test_generic_tower_on_greenlands_unchanged(self):
        """Towers outside forest / mountain keep the v1 shape:
        full TOWER_FLOOR_COUNT_RANGE, brick walls by default, no
        forced roof material."""
        lo, hi = TOWER_FLOOR_COUNT_RANGE
        any_above_2 = False
        any_non_wood_roof = False
        for seed in SEEDS:
            site = assemble_tower(
                f"gt{seed}", random.Random(seed),
                biome=Biome.GREENLANDS,
            )
            b = site.buildings[0]
            n = len(b.floors)
            assert lo <= n <= hi
            if n > 2:
                any_above_2 = True
            if getattr(b, "roof_material", None) != "wood":
                any_non_wood_roof = True
        assert any_above_2, (
            f"greenlands tower never exceeded 2 floors across "
            f"{len(SEEDS)} seeds"
        )
        assert any_non_wood_roof

    def test_assemble_tower_without_biome_matches_legacy(self):
        """Tower without biome kwarg matches legacy (no wood roof
        forced, no floor clamp)."""
        lo, hi = TOWER_FLOOR_COUNT_RANGE
        for seed in SEEDS:
            site = assemble_tower(
                f"lt{seed}", random.Random(seed),
            )
            b = site.buildings[0]
            assert lo <= len(b.floors) <= hi


class TestDispatcherForwardsBiome:
    def test_assemble_site_forwards_biome_to_tower_assembler(self):
        site = assemble_site(
            "tower", "disp", random.Random(3), biome=Biome.FOREST,
        )
        b = site.buildings[0]
        assert len(b.floors) <= 2
        assert getattr(b, "roof_material", None) == "wood"
