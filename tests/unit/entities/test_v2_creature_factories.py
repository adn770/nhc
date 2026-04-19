"""Tests for biome-features v2 creature prerequisites (M8).

The v2 faction table in design/biome_features.md §8 references three
creature ids not yet in the registry: cultist, frozen_dead, yeti. It
also expects BEAST_POOL and UNDEAD_POOL module-level constants to
expand the "beast" / "undead" category keys later wired into the
per-biome ruin faction pools.
"""

import pytest

from nhc.entities.registry import EntityRegistry
from nhc.i18n.manager import TranslationManager


V2_CREATURE_IDS = ["cultist", "frozen_dead", "yeti"]


@pytest.fixture(scope="module")
def _discover():
    EntityRegistry.discover_all()


class TestV2CreatureFactoriesRegistered:
    def test_cultist_factory_registered(self, _discover):
        assert "cultist" in EntityRegistry.list_creatures()

    def test_frozen_dead_factory_registered(self, _discover):
        assert "frozen_dead" in EntityRegistry.list_creatures()

    def test_yeti_factory_registered(self, _discover):
        assert "yeti" in EntityRegistry.list_creatures()

    @pytest.mark.parametrize("creature_id", V2_CREATURE_IDS)
    def test_each_factory_returns_required_components(
        self, _discover, creature_id
    ):
        comps = EntityRegistry.get_creature(creature_id)
        assert "Health" in comps
        assert "Stats" in comps
        assert "AI" in comps
        assert "Renderable" in comps
        assert "Description" in comps

        health = comps["Health"]
        assert health.current > 0
        assert health.maximum >= health.current


class TestV2CreatureLocaleEntries:
    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_cultist_has_en_ca_es_locale_entries(self, lang):
        mgr = TranslationManager()
        mgr.load(lang)
        assert mgr.get("creature.cultist.name") != "creature.cultist.name"
        assert mgr.get("creature.cultist.short") != "creature.cultist.short"

    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_frozen_dead_has_en_ca_es_locale_entries(self, lang):
        mgr = TranslationManager()
        mgr.load(lang)
        assert (mgr.get("creature.frozen_dead.name")
                != "creature.frozen_dead.name")
        assert (mgr.get("creature.frozen_dead.short")
                != "creature.frozen_dead.short")

    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_yeti_has_en_ca_es_locale_entries(self, lang):
        mgr = TranslationManager()
        mgr.load(lang)
        assert mgr.get("creature.yeti.name") != "creature.yeti.name"
        assert mgr.get("creature.yeti.short") != "creature.yeti.short"

    @pytest.mark.parametrize("creature_id", V2_CREATURE_IDS)
    def test_romance_entries_declare_gender(self, creature_id):
        for lang in ("ca", "es"):
            mgr = TranslationManager()
            mgr.load(lang)
            gender = mgr.get(f"creature.{creature_id}.gender")
            assert gender in ("m", "f"), (
                f"{creature_id} in {lang} must declare gender"
            )


class TestV2CategoryPools:
    def test_beast_pool_and_undead_pool_reference_only_registered_ids(
        self, _discover
    ):
        from nhc.dungeon.populator import BEAST_POOL, UNDEAD_POOL

        registered = set(EntityRegistry.list_creatures())
        for pool, name in ((BEAST_POOL, "BEAST_POOL"),
                           (UNDEAD_POOL, "UNDEAD_POOL")):
            assert pool, f"{name} must not be empty"
            for cid, weight in pool:
                assert cid in registered, (
                    f"{name} references unregistered creature {cid!r}"
                )
                assert weight > 0

    def test_beast_pool_weights_sum_close_to_one(self, _discover):
        from nhc.dungeon.populator import BEAST_POOL

        total = sum(w for _, w in BEAST_POOL)
        assert abs(total - 1.0) < 0.01

    def test_undead_pool_weights_sum_close_to_one(self, _discover):
        from nhc.dungeon.populator import UNDEAD_POOL

        total = sum(w for _, w in UNDEAD_POOL)
        assert abs(total - 1.0) < 0.01
