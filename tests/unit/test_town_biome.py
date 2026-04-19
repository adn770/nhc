"""Biome-aware overrides on the town assembler (milestone 4).

Mountain settlements ("mountain-Village", "mountain-Lodge") need
all-stone buildings and no palisade regardless of size_class.
Other biomes continue to use the size_class defaults.
"""

from __future__ import annotations

import random

from nhc.dungeon.site import assemble_site
from nhc.dungeon.sites.town import (
    TOWN_WOOD_BUILDING_PROBABILITY,
    assemble_town,
)
from nhc.hexcrawl.model import Biome


# ---------------------------------------------------------------------------
# Mountain override
# ---------------------------------------------------------------------------


class TestMountainOverride:
    def test_assemble_town_mountain_has_no_palisade(self) -> None:
        site = assemble_town(
            "t_mtn_1", random.Random(1),
            size_class="village", biome=Biome.MOUNTAIN,
        )
        assert site.enclosure is None

    def test_assemble_town_mountain_all_buildings_are_stone(
        self,
    ) -> None:
        # Check over multiple seeds to make sure the wood-building
        # probability is effectively forced to 0 on mountain.
        for seed in range(10):
            site = assemble_town(
                f"t_mtn_{seed}", random.Random(seed),
                size_class="village", biome=Biome.MOUNTAIN,
            )
            for b in site.buildings:
                assert b.wall_material == "stone", (
                    f"seed {seed} building {b.id}: "
                    f"wall_material={b.wall_material!r} "
                    f"(expected stone on mountain)"
                )
                assert b.interior_floor == "stone", (
                    f"seed {seed} building {b.id}: "
                    f"interior_floor={b.interior_floor!r}"
                )

    def test_assemble_town_mountain_village_building_count_skews_smaller(
        self,
    ) -> None:
        """Mountain settlements lean to the bottom of the size
        class building-count range -- no sprawling town on a
        peak."""
        counts_mountain: list[int] = []
        counts_default: list[int] = []
        for seed in range(20):
            mtn = assemble_town(
                f"m_{seed}", random.Random(seed),
                size_class="village", biome=Biome.MOUNTAIN,
            )
            other = assemble_town(
                f"g_{seed}", random.Random(seed),
                size_class="village", biome=Biome.GREENLANDS,
            )
            counts_mountain.append(len(mtn.buildings))
            counts_default.append(len(other.buildings))
        avg_mtn = sum(counts_mountain) / len(counts_mountain)
        avg_other = sum(counts_default) / len(counts_default)
        assert avg_mtn < avg_other, (
            f"mountain avg buildings {avg_mtn} not smaller than "
            f"greenlands avg {avg_other}"
        )


# ---------------------------------------------------------------------------
# Default behaviour preserved
# ---------------------------------------------------------------------------


class TestDefaultsPreserved:
    def test_assemble_town_greenlands_defaults_unchanged(
        self,
    ) -> None:
        """Greenlands village retains its palisade and the wood /
        stone mix driven by TOWN_WOOD_BUILDING_PROBABILITY."""
        site = assemble_town(
            "g1", random.Random(0),
            size_class="village", biome=Biome.GREENLANDS,
        )
        assert site.enclosure is not None
        assert site.enclosure.kind == "palisade"
        # Some wood and some stone are expected across many seeds;
        # we only check that stone isn't forced on every building.
        materials = {b.wall_material for b in site.buildings}
        # At 65% wood probability, either set is plausible for a
        # single seed; check a handful of seeds instead.
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
            f"expected at least one wood-walled building over "
            f"10 seeds (TOWN_WOOD_BUILDING_PROBABILITY="
            f"{TOWN_WOOD_BUILDING_PROBABILITY})"
        )
        del materials  # avoid unused-local warning

    def test_assemble_town_without_biome_kwarg_matches_legacy(
        self,
    ) -> None:
        """Callers that don't pass biome get the legacy behaviour
        (village palisade, mixed materials) -- back-compat with
        pre-M4 tests."""
        site = assemble_town(
            "g_legacy", random.Random(0), size_class="village",
        )
        assert site.enclosure is not None
        assert site.enclosure.kind == "palisade"


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------


class TestAssembleSiteForwardsBiome:
    def test_assemble_site_forwards_biome_to_town(self) -> None:
        """assemble_site("town", ..., biome=MOUNTAIN) must pass
        the biome through to the town assembler's mountain
        overrides."""
        site = assemble_site(
            "town", "dispatched", random.Random(3),
            size_class="village", biome=Biome.MOUNTAIN,
        )
        assert site.enclosure is None
        for b in site.buildings:
            assert b.wall_material == "stone"

    def test_assemble_site_biome_defaults_to_none(self) -> None:
        """Omitting biome must keep the legacy behaviour."""
        site = assemble_site(
            "town", "default", random.Random(0),
            size_class="village",
        )
        assert site.enclosure is not None


# ---------------------------------------------------------------------------
# Game-layer wiring: cell.biome -> assemble_site
# ---------------------------------------------------------------------------


class TestEnterWalledSitePassesBiome:
    def test_enter_walled_site_passes_cell_biome_to_assembler(
        self, tmp_path,
    ) -> None:
        """When a mountain village hex is entered, the game must
        pass cell.biome into assemble_site so the mountain
        override kicks in."""
        import asyncio

        from nhc.core.game import Game
        from nhc.entities.registry import EntityRegistry
        from nhc.hexcrawl.coords import HexCoord
        from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
        from nhc.hexcrawl.model import (
            DungeonRef, HexCell, HexFeatureType, HexWorld,
        )
        from nhc.i18n import init as i18n_init

        i18n_init("en")
        EntityRegistry.discover_all()

        class _FakeClient:
            game_mode = "classic"
            lang = "en"
            edge_doors = False
            messages: list[str] = []

            def __getattr__(self, name):
                if name.startswith("_"):
                    raise AttributeError(name)

                def _sync(*a, **kw):
                    return None

                return _sync

        async def _run() -> None:
            g = Game(
                client=_FakeClient(), backend=None,
                style="classic",
                world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
                save_dir=tmp_path, seed=42,
            )
            g.hex_world = HexWorld(
                pack_id="t", seed=42, width=1, height=1,
            )
            cell = HexCell(
                coord=HexCoord(0, 0), biome=Biome.MOUNTAIN,
                feature=HexFeatureType.VILLAGE,
                dungeon=DungeonRef(
                    template="procedural:settlement",
                    size_class="village",
                    site_kind="town",
                ),
            )
            g.hex_world.set_cell(cell)
            g.hex_world.visit(cell.coord)
            entered = await g._enter_walled_site(cell.coord, "town")
            assert entered is True
            assert g._active_site is not None
            assert g._active_site.enclosure is None
            for b in g._active_site.buildings:
                assert b.wall_material == "stone"

        asyncio.run(_run())
