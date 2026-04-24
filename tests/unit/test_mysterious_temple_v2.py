"""Mysterious temple content differentiation (M15 of v2).

v1's M5 shipped mysterious temples (sandlands + icelands) as
tile-only partial walls -- same priest, same services, same
prices. v2 backs the flavour with content-level differentiation
from design/biome_features.md §8:

* Mysterious temples place a hermit_priest (different
  entity_id) with temple_services restricted to ["bless"].
* Ground-floor room carries a biome-specific dressing tag:
  "cursed_altar" on icelands, "buried_relic" on sandlands.
* Partial walls persist from v1 (regression check).
* Mountain and forest temples stay full-service (regression).
"""

from __future__ import annotations

import random

import pytest

from nhc.sites.temple import assemble_temple
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.model import Biome
from nhc.i18n import init as i18n_init


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


def _priest(site):
    return next(
        (e for e in site.buildings[0].ground.entities
         if e.entity_id in ("priest", "hermit_priest")),
        None,
    )


# ── Expected-variant regression: mountain + forest full-service ───────


class TestExpectedVariantsStayFullService:
    def test_mountain_temple_has_full_service_priest(self):
        site = assemble_temple(
            "mt", random.Random(1), biome=Biome.MOUNTAIN,
        )
        p = _priest(site)
        assert p is not None
        assert p.entity_id == "priest"
        assert set(p.extra["temple_services"]) == {
            "heal", "remove_curse", "bless",
        }

    def test_forest_temple_has_full_service_priest(self):
        site = assemble_temple(
            "ft", random.Random(1), biome=Biome.FOREST,
        )
        p = _priest(site)
        assert p is not None
        assert p.entity_id == "priest"
        assert set(p.extra["temple_services"]) == {
            "heal", "remove_curse", "bless",
        }


# ── Mysterious variants: hermit_priest + bless-only ───────────────────


class TestMysteriousPriestContent:
    def test_sandlands_temple_has_hermit_priest_with_bless_only(self):
        site = assemble_temple(
            "st", random.Random(1), biome=Biome.SANDLANDS,
        )
        p = _priest(site)
        assert p is not None
        assert p.entity_id == "hermit_priest"
        assert list(p.extra["temple_services"]) == ["bless"]

    def test_icelands_temple_has_hermit_priest_with_bless_only(self):
        site = assemble_temple(
            "it", random.Random(1), biome=Biome.ICELANDS,
        )
        p = _priest(site)
        assert p is not None
        assert p.entity_id == "hermit_priest"
        assert list(p.extra["temple_services"]) == ["bless"]


# ── Lore dressing tags ────────────────────────────────────────────────


class TestMysteriousTempleDressing:
    def test_icelands_temple_room_has_cursed_altar_tag(self):
        site = assemble_temple(
            "it", random.Random(1), biome=Biome.ICELANDS,
        )
        room = site.buildings[0].ground.rooms[0]
        assert "cursed_altar" in room.tags

    def test_sandlands_temple_room_has_buried_relic_tag(self):
        site = assemble_temple(
            "st", random.Random(1), biome=Biome.SANDLANDS,
        )
        room = site.buildings[0].ground.rooms[0]
        assert "buried_relic" in room.tags

    def test_expected_temples_have_no_mysterious_dressing_tag(self):
        for biome in (Biome.MOUNTAIN, Biome.FOREST):
            site = assemble_temple(
                f"e_{biome.value}", random.Random(1), biome=biome,
            )
            room = site.buildings[0].ground.rooms[0]
            assert "cursed_altar" not in room.tags
            assert "buried_relic" not in room.tags


# ── Regressions: partial walls + locale + factory ─────────────────────


class TestRegressionsPartialWallsAndLocales:
    @pytest.mark.parametrize("biome", [Biome.SANDLANDS, Biome.ICELANDS])
    def test_mysterious_temples_still_have_partial_walls(self, biome):
        from nhc.dungeon.model import Terrain
        site = assemble_temple(
            f"pw_{biome.value}", random.Random(0), biome=biome,
        )
        b = site.buildings[0]
        ground = b.ground
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
        assert 2 <= void_count <= 4

    def test_hermit_priest_factory_is_registered(self):
        assert "hermit_priest" in EntityRegistry.list_creatures()

    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_hermit_priest_has_locale_entries(self, lang):
        from nhc.i18n.manager import TranslationManager
        mgr = TranslationManager()
        mgr.load(lang)
        assert (mgr.get("creature.hermit_priest.name")
                != "creature.hermit_priest.name")
        assert (mgr.get("creature.hermit_priest.short")
                != "creature.hermit_priest.short")

    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_lore_strings_exist(self, lang):
        from nhc.i18n.manager import TranslationManager
        mgr = TranslationManager()
        mgr.load(lang)
        assert (mgr.get("temple.dressing.cursed_altar")
                != "temple.dressing.cursed_altar")
        assert (mgr.get("temple.dressing.buried_relic")
                != "temple.dressing.buried_relic")
