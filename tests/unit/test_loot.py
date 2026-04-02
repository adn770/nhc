"""Tests for loot generation."""

import pytest

from nhc.core.ecs import World
from nhc.entities.components import (
    Description,
    LootTable,
    Position,
    Renderable,
)
from nhc.entities.registry import EntityRegistry
from nhc.rules.loot import generate_loot
from nhc.utils.rng import set_seed


class TestGenerateLoot:
    def test_guaranteed_drop(self):
        """Entry with probability 1.0 always drops."""
        set_seed(42)
        world = World()
        # Register a fake item via direct entity
        EntityRegistry._items["test_item"] = lambda: {
            "Renderable": Renderable(glyph="!", color="white"),
            "Description": Description(name="Test Item"),
        }

        table = LootTable(entries=[("test_item", 1.0)])
        spawned = generate_loot(world, table, x=5, y=5, level_id="test")

        assert len(spawned) == 1
        pos = world.get_component(spawned[0], "Position")
        assert pos.x == 5
        assert pos.y == 5
        desc = world.get_component(spawned[0], "Description")
        assert desc.name == "Test Item"

        del EntityRegistry._items["test_item"]

    def test_zero_probability_never_drops(self):
        """Entry with probability 0 never drops."""
        set_seed(42)
        world = World()
        EntityRegistry._items["no_drop"] = lambda: {
            "Renderable": Renderable(glyph="!"),
            "Description": Description(name="No Drop"),
        }

        table = LootTable(entries=[("no_drop", 0.0)])
        spawned = generate_loot(world, table, x=5, y=5)

        assert len(spawned) == 0
        del EntityRegistry._items["no_drop"]

    def test_unknown_item_skipped(self):
        """Unknown item IDs in the loot table are silently skipped."""
        set_seed(42)
        world = World()
        table = LootTable(entries=[("nonexistent_item", 1.0)])
        spawned = generate_loot(world, table, x=5, y=5)
        assert len(spawned) == 0

    def test_quantity_dice(self):
        """Entries with dice notation produce quantity-modified names."""
        set_seed(42)
        world = World()
        EntityRegistry._items["gold_test"] = lambda: {
            "Renderable": Renderable(glyph="$"),
            "Description": Description(name="Gold"),
        }

        table = LootTable(entries=[("gold_test", 1.0, "2d6")])
        spawned = generate_loot(world, table, x=3, y=3)

        assert len(spawned) == 1
        desc = world.get_component(spawned[0], "Description")
        # Name should be prefixed with quantity
        assert desc.name.startswith(("1 ", "2 ", "3 ", "4 ", "5 ", "6 ",
                                     "7 ", "8 ", "9 ", "10 ", "11 ", "12 "))
        assert "Gold" in desc.name

        del EntityRegistry._items["gold_test"]

    def test_multiple_entries(self):
        """Multiple guaranteed entries all spawn."""
        set_seed(42)
        world = World()
        EntityRegistry._items["item_a"] = lambda: {
            "Renderable": Renderable(glyph="a"),
            "Description": Description(name="Item A"),
        }
        EntityRegistry._items["item_b"] = lambda: {
            "Renderable": Renderable(glyph="b"),
            "Description": Description(name="Item B"),
        }

        table = LootTable(entries=[("item_a", 1.0), ("item_b", 1.0)])
        spawned = generate_loot(world, table, x=1, y=1)

        assert len(spawned) == 2

        del EntityRegistry._items["item_a"]
        del EntityRegistry._items["item_b"]
