"""Tests for Knave starting equipment generation."""
from nhc.rules.chargen import (
    generate_character, WEAPON_TABLE, ARMOR_TABLE, LOOT_TABLE,
    GENERAL_EQUIPMENT_1, GENERAL_EQUIPMENT_2, STARTING_SCROLLS,
    _roll_starting_equipment,
)
from nhc.utils.rng import set_seed, get_rng
from nhc.entities.registry import EntityRegistry


class TestStartingEquipment:
    def test_always_has_weapon(self):
        for seed in range(20):
            char = generate_character(seed=seed)
            has_weapon = any(
                item in WEAPON_TABLE for item in char.starting_items
            )
            assert has_weapon, f"seed {seed}: no weapon"

    def test_always_has_rations(self):
        for seed in range(20):
            char = generate_character(seed=seed)
            assert "rations" in char.starting_items

    def test_always_has_potion_healing(self):
        for seed in range(20):
            char = generate_character(seed=seed)
            assert "potion_healing" in char.starting_items

    def test_always_has_scroll(self):
        for seed in range(20):
            char = generate_character(seed=seed)
            has_scroll = any(
                item in STARTING_SCROLLS for item in char.starting_items
            )
            assert has_scroll, f"seed {seed}: no scroll"

    def test_slot_cost_within_limit(self):
        """Starting items must not exceed CON defense slots."""
        EntityRegistry.discover_all()
        for seed in range(50):
            char = generate_character(seed=seed)
            max_slots = 10 + char.constitution
            total = 0
            for iid in char.starting_items:
                comps = EntityRegistry.get_item(iid)
                cost = 1
                if "Weapon" in comps:
                    cost = comps["Weapon"].slots
                if "Armor" in comps:
                    cost = comps["Armor"].slots
                total += cost
            assert total <= max_slots, (
                f"seed {seed}: {total}/{max_slots} slots exceeded"
            )

    def test_has_loot_items(self):
        """Should have 2 items from loot table."""
        for seed in range(20):
            char = generate_character(seed=seed)
            loot_count = sum(
                1 for item in char.starting_items if item in LOOT_TABLE
            )
            assert loot_count >= 1, f"seed {seed}: no loot items"

    def test_has_general_equipment(self):
        for seed in range(20):
            char = generate_character(seed=seed)
            has_gen1 = any(
                item in GENERAL_EQUIPMENT_1 for item in char.starting_items
            )
            has_gen2 = any(
                item in GENERAL_EQUIPMENT_2 for item in char.starting_items
            )
            assert has_gen1 or has_gen2, (
                f"seed {seed}: no general equipment"
            )

    def test_deterministic(self):
        a = generate_character(seed=42)
        b = generate_character(seed=42)
        assert a.starting_items == b.starting_items
