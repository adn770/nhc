"""Per-biome town overrides beyond mountain (M13 of biome-features v2).

v1's M4 landed the mountain-only town override. v2 extends the
biome= kwarg on assemble_town to cover drylands (adobe walls,
sand-packed earth interior, palisade kept) and marsh (stilted-
wood construction with an ambient marker the frontend can use to
raise the surface a tile). Greenlands and mountain defaults stay
unchanged -- this file covers the regressions.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites._site import assemble_site
from nhc.sites.town import (
    TOWN_WOOD_BUILDING_PROBABILITY, assemble_town,
)
from nhc.hexcrawl.model import Biome


SEEDS = range(12)


# ── Drylands ──────────────────────────────────────────────────────────


class TestDrylandsOverride:
    def test_drylands_village_uses_adobe_wall_material(self):
        for seed in SEEDS:
            site = assemble_town(
                f"d{seed}", random.Random(seed),
                size_class="village", biome=Biome.DRYLANDS,
            )
            for b in site.buildings:
                assert b.wall_material == "adobe", (
                    f"seed={seed} building {b.id}: "
                    f"wall_material={b.wall_material!r} "
                    f"(expected adobe)"
                )

    def test_drylands_village_keeps_palisade(self):
        for seed in SEEDS:
            site = assemble_town(
                f"d{seed}", random.Random(seed),
                size_class="village", biome=Biome.DRYLANDS,
            )
            assert site.enclosure is not None
            assert site.enclosure.kind == "palisade"

    def test_drylands_interior_is_sand_packed_earth(self):
        site = assemble_town(
            "d1", random.Random(1),
            size_class="village", biome=Biome.DRYLANDS,
        )
        for b in site.buildings:
            assert b.interior_floor == "earth"


# ── Marsh ─────────────────────────────────────────────────────────────


class TestMarshOverride:
    def test_marsh_village_has_stilted_wood_wall_material(self):
        for seed in SEEDS:
            site = assemble_town(
                f"m{seed}", random.Random(seed),
                size_class="village", biome=Biome.MARSH,
            )
            for b in site.buildings:
                assert b.wall_material == "wood", (
                    f"seed={seed}: expected wood walls on marsh, "
                    f"got {b.wall_material!r}"
                )

    def test_marsh_village_surface_has_stilted_ambient_marker(self):
        site = assemble_town(
            "m1", random.Random(1),
            size_class="village", biome=Biome.MARSH,
        )
        assert site.surface.metadata is not None
        assert site.surface.metadata.ambient == "stilted"

    def test_marsh_village_keeps_palisade(self):
        site = assemble_town(
            "m1", random.Random(1),
            size_class="village", biome=Biome.MARSH,
        )
        assert site.enclosure is not None
        assert site.enclosure.kind == "palisade"


# ── Regressions: greenlands / mountain unchanged ──────────────────────


class TestRegressionsUnchanged:
    def test_greenlands_village_still_defaults_to_wood_brick_mix(self):
        saw_wood = False
        for seed in range(10):
            s = assemble_town(
                f"g_{seed}", random.Random(seed),
                size_class="village", biome=Biome.GREENLANDS,
            )
            if any(b.wall_material == "brick" for b in s.buildings):
                saw_wood = True
                break
        assert saw_wood, (
            f"expected at least one wood-walled (brick) building "
            f"across 10 seeds at "
            f"TOWN_WOOD_BUILDING_PROBABILITY="
            f"{TOWN_WOOD_BUILDING_PROBABILITY}"
        )

    def test_mountain_village_still_has_no_palisade_and_stone_walls(
        self,
    ):
        site = assemble_town(
            "mt", random.Random(1),
            size_class="village", biome=Biome.MOUNTAIN,
        )
        assert site.enclosure is None
        for b in site.buildings:
            assert b.wall_material == "stone"
            assert b.interior_floor == "stone"


# ── Dispatcher wiring ─────────────────────────────────────────────────


class TestAssembleSiteForwardsBiome:
    def test_assemble_site_forwards_drylands_biome(self):
        site = assemble_site(
            "town", "dispatched_dry", random.Random(3),
            size_class="village", biome=Biome.DRYLANDS,
        )
        for b in site.buildings:
            assert b.wall_material == "adobe"

    def test_assemble_site_forwards_marsh_biome(self):
        site = assemble_site(
            "town", "dispatched_marsh", random.Random(3),
            size_class="village", biome=Biome.MARSH,
        )
        assert site.surface.metadata.ambient == "stilted"
