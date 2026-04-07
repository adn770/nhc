"""Tests for entity registry auto-discovery."""

from nhc.entities.components import Consumable, Health, Stats, Trap, Weapon
from nhc.entities.registry import EntityRegistry


class TestEntityRegistry:
    @classmethod
    def setup_class(cls):
        EntityRegistry.discover_all()

    def test_creatures_discovered(self):
        creatures = EntityRegistry.list_creatures()
        assert "goblin" in creatures
        assert "skeleton" in creatures

    def test_items_discovered(self):
        items = EntityRegistry.list_items()
        assert "sword" in items
        assert "potion_healing" in items

    def test_features_discovered(self):
        features = EntityRegistry.list_features()
        assert "trap_pit" in features

    def test_creature_factory_returns_components(self):
        goblin = EntityRegistry.get_creature("goblin")
        assert "Stats" in goblin
        assert "Health" in goblin
        assert "Renderable" in goblin
        assert isinstance(goblin["Stats"], Stats)
        assert isinstance(goblin["Health"], Health)

    def test_item_factory_returns_components(self):
        sword = EntityRegistry.get_item("sword")
        assert "Weapon" in sword
        assert isinstance(sword["Weapon"], Weapon)
        assert sword["Weapon"].damage == "1d8"

    def test_consumable_factory(self):
        potion = EntityRegistry.get_item("potion_healing")
        assert "Consumable" in potion
        assert isinstance(potion["Consumable"], Consumable)
        assert potion["Consumable"].effect == "heal"

    def test_feature_factory(self):
        trap = EntityRegistry.get_feature("trap_pit")
        assert "Trap" in trap
        assert isinstance(trap["Trap"], Trap)
        assert trap["Trap"].dc == 12
