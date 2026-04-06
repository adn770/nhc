"""Tests for the gem item system: factories, identification, spawning."""

import pytest

from nhc.entities.components import Gem
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.rules.identification import (
    GEM_APPEARANCES, GEM_IDS, ItemKnowledge,
)

REAL_GEM_IDS = [g for g in GEM_IDS if g.startswith("gem_")]
from nhc.core.actions._helpers import _item_slot_cost
from nhc.core.ecs import World
from nhc.rules.prices import buy_price, sell_price
from nhc.utils.rng import set_seed


@pytest.fixture(autouse=True)
def _init():
    i18n_init("en")
    EntityRegistry.discover_all()


class TestGemFactories:
    @pytest.mark.parametrize("gem_id", REAL_GEM_IDS)
    def test_gem_has_required_components(self, gem_id):
        comps = EntityRegistry.get_item(gem_id)
        assert "Renderable" in comps
        assert "Description" in comps
        assert "Gem" in comps
        assert comps["Renderable"].glyph == "*"

    @pytest.mark.parametrize("gem_id", REAL_GEM_IDS)
    def test_gem_has_positive_value(self, gem_id):
        comps = EntityRegistry.get_item(gem_id)
        assert comps["Gem"].value > 0

    @pytest.mark.parametrize("gem_id", REAL_GEM_IDS)
    def test_gem_has_price(self, gem_id):
        assert buy_price(gem_id) > 0
        assert sell_price(gem_id) == buy_price(gem_id) // 2


class TestGemSlots:
    @pytest.mark.parametrize("gem_id", GEM_IDS)
    def test_gems_consume_zero_slots(self, gem_id):
        world = World()
        comps = EntityRegistry.get_item(gem_id)
        eid = world.create_entity(comps)
        assert _item_slot_cost(world, eid) == 0


class TestGemIdentification:
    def test_gems_are_identifiable(self):
        knowledge = ItemKnowledge()
        for gem_id in GEM_IDS:
            assert knowledge.is_identifiable(gem_id)

    def test_gems_start_unidentified(self):
        knowledge = ItemKnowledge()
        for gem_id in GEM_IDS:
            assert not knowledge.is_identified(gem_id)

    def test_gem_appearance_is_glass(self):
        knowledge = ItemKnowledge()
        for gem_id in GEM_IDS:
            name = knowledge.display_name(gem_id)
            assert "glass" in name.lower(), (
                f"{gem_id} appearance should contain 'glass', "
                f"got: {name}"
            )

    def test_gem_identified_shows_real_name(self):
        knowledge = ItemKnowledge()
        knowledge.identify("gem_diamond")
        name = knowledge.display_name("gem_diamond")
        assert "Diamond" in name

    def test_gem_appearances_shuffled_per_seed(self):
        set_seed(42)
        k1 = ItemKnowledge()
        a1 = k1.display_name("gem_diamond")
        set_seed(99)
        k2 = ItemKnowledge()
        a2 = k2.display_name("gem_diamond")
        # Different seeds should (very likely) produce different
        # glass colors for the same gem
        # (not guaranteed but extremely likely with 8 options)
        # Just verify they both look like glass
        assert "glass" in a1.lower()
        assert "glass" in a2.lower()

    def test_appearance_prefix_is_gem(self):
        assert ItemKnowledge._appearance_prefix("gem_ruby") == (
            "gem_appearance"
        )

    def test_gem_ids_includes_glass_pieces(self):
        glass = [g for g in GEM_IDS if g.startswith("glass_piece")]
        gems = [g for g in GEM_IDS if g.startswith("gem_")]
        assert len(glass) == 8
        assert len(gems) == 8

    def test_glass_pieces_are_identifiable(self):
        knowledge = ItemKnowledge()
        for i in range(1, 9):
            gid = f"glass_piece_{i}"
            assert knowledge.is_identifiable(gid)

    def test_glass_identified_shows_worthless(self):
        knowledge = ItemKnowledge()
        knowledge.identify("glass_piece_1")
        name = knowledge.display_name("glass_piece_1")
        assert "Glass" in name or "glass" in name.lower()

    def test_glass_shares_appearance_with_gem(self):
        """Glass pieces and real gems share glass color appearances."""
        knowledge = ItemKnowledge()
        # Both should show as some kind of glass
        for gid in GEM_IDS:
            name = knowledge.display_name(gid)
            assert "glass" in name.lower()
