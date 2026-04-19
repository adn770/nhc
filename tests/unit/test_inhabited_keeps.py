"""Inhabited keep surfaces (M12 of biome-features v2).

design/biome_features.md §8 flags "inhabited keeps" as the v1
gap opposite the abandoned-ruin treatment: keep surfaces were
empty of NPCs even though the hex-level "inhabited fortified
compound" contract implied they shouldn't be. M12 runs a
dedicated surface-NPC pass on keep assembly: 2-4 guards across
the courtyard, one quartermaster a tile off the first gate,
one commander near the largest main building. Keep interiors
stay unchanged so the descent into the cellar still reads as a
barracks accessway, not populated quarters.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from nhc.core.game import Game
from nhc.dungeon.sites.keep import assemble_keep
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import (
    Biome, DungeonRef, HexCell, HexFeatureType, HexWorld,
)
from nhc.i18n import init as i18n_init


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


def _surface_entities(site):
    return [e for e in site.surface.entities]


# ── Guards / quartermaster / commander placement ──────────────────────


class TestKeepSurfaceNPCs:
    def test_keep_surface_has_at_least_two_guards(self):
        for seed in (1, 7, 42, 99):
            site = assemble_keep(f"k{seed}", random.Random(seed))
            guards = [
                e for e in _surface_entities(site)
                if e.entity_id == "guard"
            ]
            assert len(guards) >= 2

    def test_keep_surface_has_exactly_one_quartermaster(self):
        for seed in (1, 7, 42, 99):
            site = assemble_keep(f"k{seed}", random.Random(seed))
            qm = [
                e for e in _surface_entities(site)
                if e.entity_id == "quartermaster"
            ]
            assert len(qm) == 1, (
                f"seed={seed}: expected 1 quartermaster, got "
                f"{len(qm)}"
            )

    def test_keep_surface_has_exactly_one_commander(self):
        for seed in (1, 7, 42, 99):
            site = assemble_keep(f"k{seed}", random.Random(seed))
            cmdrs = [
                e for e in _surface_entities(site)
                if e.entity_id == "commander"
            ]
            assert len(cmdrs) == 1

    def test_keep_buildings_still_empty_of_civilians(self):
        """Guards / commanders live outdoors. Keep interiors stay
        unchanged so the cellar still reads as barracks accessway."""
        for seed in (1, 7, 42, 99):
            site = assemble_keep(f"k{seed}", random.Random(seed))
            for b in site.buildings:
                for f in b.floors:
                    assert f.entities == []

    def test_quartermaster_is_near_the_first_gate(self):
        """The quartermaster should stand within a small Chebyshev
        distance of the first gate midpoint so the player meets them
        on entry."""
        for seed in (1, 7, 42, 99):
            site = assemble_keep(f"k{seed}", random.Random(seed))
            gx, gy, _ = site.enclosure.gates[0]
            qm = next(
                e for e in site.surface.entities
                if e.entity_id == "quartermaster"
            )
            assert max(abs(qm.x - gx), abs(qm.y - gy)) <= 3

    def test_commander_is_near_a_main_building(self):
        """Commander sits within Chebyshev distance 3 of a main
        building's footprint so they read as the compound's lead."""
        for seed in (1, 7, 42, 99):
            site = assemble_keep(f"k{seed}", random.Random(seed))
            cmdr = next(
                e for e in site.surface.entities
                if e.entity_id == "commander"
            )
            main_rects = [
                b.base_rect for b in site.buildings
                if "keep_main" in b.id
            ]
            assert main_rects
            def _dist(r):
                cx = r.x + r.width // 2
                cy = r.y + r.height // 2
                return max(abs(cmdr.x - cx), abs(cmdr.y - cy))
            assert min(_dist(r) for r in main_rects) <= 6


# ── Creature contracts ────────────────────────────────────────────────


class TestKeepNPCFactories:
    @pytest.mark.parametrize("eid", ["guard", "quartermaster", "commander"])
    def test_npc_factory_registered(self, eid):
        assert eid in EntityRegistry.list_creatures()
        comps = EntityRegistry.get_creature(eid)
        assert "Health" in comps and "AI" in comps

    @pytest.mark.parametrize("eid", ["guard", "quartermaster", "commander"])
    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_npc_has_locale_entries(self, eid, lang):
        from nhc.i18n.manager import TranslationManager
        mgr = TranslationManager()
        mgr.load(lang)
        assert mgr.get(f"creature.{eid}.name") != f"creature.{eid}.name"
        assert mgr.get(f"creature.{eid}.short") != f"creature.{eid}.short"


# ── Rumor seeding on keep entry ───────────────────────────────────────


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


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(), backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path, seed=42,
    )
    g.initialize()
    return g


class TestKeepRumorSeed:
    def test_keep_entry_seeds_rumors(self, tmp_path):
        """Entering a keep refreshes the overland rumor pool the
        same way town entry does."""
        g = _make_game(tmp_path)
        g.hex_world = HexWorld(
            pack_id="t", seed=42, width=1, height=1,
        )
        cell = HexCell(
            coord=HexCoord(0, 0), biome=Biome.GREENLANDS,
            feature=HexFeatureType.KEEP,
            dungeon=DungeonRef(
                template="site:keep", site_kind="keep",
            ),
        )
        g.hex_world.set_cell(cell)
        g.hex_world.visit(cell.coord)
        g.hex_player_position = cell.coord

        assert g.hex_world.active_rumors == []

        async def _run():
            await g._enter_walled_site(cell.coord, "keep")

        asyncio.run(_run())
        assert g.hex_world.active_rumors, (
            "keep entry should have seeded active_rumors"
        )
