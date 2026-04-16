"""Tests for humanoid creature loot tables."""

from __future__ import annotations

import pytest

from nhc.entities.registry import EntityRegistry

# Humanoid factions per ai/behavior.py
HUMANOID_FACTIONS = {
    "goblinoid", "human", "humanoid", "giant", "gnoll",
}

# Items that count as weapons or armor
EQUIPMENT_PREFIXES = (
    "dagger", "short_sword", "sword", "long_sword", "spear",
    "mace", "axe", "hand_axe", "halberd", "war_hammer",
    "club", "staff", "sling", "bow", "crossbow", "javelin",
    "shield", "helmet", "gambeson", "brigandine", "chain_mail",
    "plate_cuirass", "full_plate", "leather_armor",
)


@pytest.fixture(autouse=True)
def _discover():
    EntityRegistry.discover_all()


class TestHumanoidLoot:
    """All humanoid creatures should have some chance to drop gear."""

    def test_humanoids_can_drop_equipment(self):
        missing = []
        for cid in EntityRegistry.list_creatures():
            comps = EntityRegistry.get_creature(cid)
            ai = comps.get("AI")
            if not ai or ai.faction not in HUMANOID_FACTIONS:
                continue
            # Skip special NPCs (town services + recruitable
            # adventurer) -- they're peaceful humanoids that don't
            # drop combat gear.
            if cid in (
                "merchant", "adventurer", "priest", "innkeeper",
            ):
                continue
            loot = comps.get("LootTable")
            if not loot:
                missing.append(cid)
                continue
            has_gear = any(
                entry[0].startswith(EQUIPMENT_PREFIXES)
                for entry in loot.entries
            )
            if not has_gear:
                missing.append(cid)
        assert not missing, (
            f"Humanoids without equipment drops: {missing}"
        )
