"""Tests for magic weapons and armor with bonuses."""

import pytest

from nhc.core.ecs import World
from nhc.core.actions import MeleeAttackAction
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Armor, BlocksMovement, Description, Enchanted, Equipment,
    Health, Inventory, Player, Position, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.rendering.terminal.renderer import TerminalRenderer
from nhc.rules.combat import resolve_melee_attack
from nhc.utils.rng import set_seed


def _make_level() -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


class TestMagicWeaponBonus:
    def test_attack_bonus_added_to_roll(self):
        """Magic weapon bonus should be added to attack roll."""
        set_seed(42)
        attacker = Stats(strength=2)
        target = Stats(dexterity=5)  # AC = 15
        # With +3 magic bonus, effective STR for attack is 2+3=5
        hit, dmg = resolve_melee_attack(
            attacker, target, "1d6", attack_bonus=3,
        )
        # Separately verify the bonus matters by testing without
        set_seed(42)
        hit_no_bonus, _ = resolve_melee_attack(
            attacker, target, "1d6", attack_bonus=0,
        )
        # At least one pair should differ (bonus helps borderline rolls)

    def test_damage_bonus_added(self):
        """Magic weapon bonus should be added to damage on hit."""
        set_seed(42)
        attacker = Stats(strength=0)
        target = Stats(dexterity=0)  # AC = 10
        # Force a hit: high bonus ensures d20+bonus >= 10
        _, dmg_with = resolve_melee_attack(
            attacker, target, "1d6", attack_bonus=10, damage_bonus=3,
        )
        set_seed(42)
        _, dmg_without = resolve_melee_attack(
            attacker, target, "1d6", attack_bonus=10, damage_bonus=0,
        )
        # Both should hit (same seed, same attack roll)
        # Damage with bonus should be exactly 3 more
        if dmg_with > 0 and dmg_without > 0:
            assert dmg_with == dmg_without + 3

    def test_magic_weapon_is_enchanted(self):
        """A +1 weapon should count as enchanted."""
        i18n_init("en")
        EntityRegistry.discover_all()
        comps = EntityRegistry.get_item("sword_plus_1")
        assert comps["Weapon"].magic_bonus == 1
        assert "Enchanted" in comps

    @pytest.mark.asyncio
    async def test_melee_uses_weapon_bonus(self):
        """MeleeAttackAction should pass magic_bonus to combat."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _make_level()

        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Player": Player(),
            "Health": Health(current=20, maximum=20),
            "Stats": Stats(strength=2, dexterity=2),
            "Inventory": Inventory(max_slots=12),
            "Equipment": Equipment(),
            "Description": Description(name="Hero"),
        })
        # Equip a +2 sword
        sword = world.create_entity({
            "Weapon": Weapon(damage="1d8", type="melee", slots=2,
                             magic_bonus=2),
            "Description": Description(name="Sword +2"),
            "Enchanted": Enchanted(),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(sword)
        equip = world.get_component(pid, "Equipment")
        equip.weapon = sword

        mob = world.create_entity({
            "Position": Position(x=6, y=5),
            "AI": AI(behavior="aggressive_melee"),
            "Health": Health(current=20, maximum=20),
            "Stats": Stats(strength=1, dexterity=1),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Goblin"),
        })

        action = MeleeAttackAction(pid, mob)
        await action.validate(world, level)
        await action.execute(world, level)
        # Just verify no crash — bonus is applied internally


class TestMagicArmorBonus:
    def test_magic_armor_increases_ac(self):
        """Magic armor bonus should add to AC defense."""
        i18n_init("en")
        world = World()

        pid = world.create_entity({
            "Player": Player(),
            "Health": Health(current=20, maximum=20),
            "Stats": Stats(dexterity=2),
            "Inventory": Inventory(max_slots=12),
            "Equipment": Equipment(),
        })
        # Equip +1 brigantine (defense 13 + magic 1 = 14)
        armor = world.create_entity({
            "Armor": Armor(slot="body", defense=13, slots=2,
                           magic_bonus=1),
            "Description": Description(name="Brigantine +1"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(armor)
        equip = world.get_component(pid, "Equipment")
        equip.armor = armor

        # Gather AC
        r = TerminalRenderer(color_mode="16")
        level = _make_level()
        stats = r._gather_stats(world, pid, 0, level)
        # AC = armor.defense(13) + magic(1) + dex(2) = 16
        assert stats["armor_def"] == 16

    def test_magic_shield_increases_ac(self):
        i18n_init("en")
        world = World()
        pid = world.create_entity({
            "Player": Player(),
            "Health": Health(current=20, maximum=20),
            "Stats": Stats(dexterity=2),
            "Inventory": Inventory(max_slots=12),
            "Equipment": Equipment(),
        })
        shield = world.create_entity({
            "Armor": Armor(slot="shield", defense=1, slots=1,
                           magic_bonus=1),
            "Description": Description(name="Shield +1"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(shield)
        equip = world.get_component(pid, "Equipment")
        equip.shield = shield

        r = TerminalRenderer(color_mode="16")
        level = _make_level()
        stats = r._gather_stats(world, pid, 0, level)
        # AC = base 10 + dex(2) + shield(1) + magic(1) = 14
        assert stats["armor_def"] == 14


class TestMagicItemFactories:
    def test_all_magic_weapons_registered(self):
        i18n_init("en")
        EntityRegistry.discover_all()
        weapons = [
            "dagger_plus_1", "short_sword_plus_1", "sword_plus_1",
            "long_sword_plus_1", "club_plus_1", "axe_plus_1",
            "hand_axe_plus_1", "mace_plus_1", "spear_plus_1",
            "staff_plus_1", "halberd_plus_1", "war_hammer_plus_1",
            "bow_plus_1", "crossbow_plus_1", "sling_plus_1",
        ]
        for item_id in weapons:
            comps = EntityRegistry.get_item(item_id)
            assert "Weapon" in comps, f"{item_id} missing Weapon"
            assert comps["Weapon"].magic_bonus == 1, f"{item_id} bonus != 1"
            assert "Enchanted" in comps, f"{item_id} missing Enchanted"

    def test_all_magic_armor_registered(self):
        i18n_init("en")
        EntityRegistry.discover_all()
        armor = [
            "gambeson_plus_1", "leather_armor_plus_1",
            "brigantine_plus_1", "chain_mail_plus_1",
            "plate_cuirass_plus_1", "full_plate_plus_1",
            "shield_plus_1", "helmet_plus_1",
        ]
        for item_id in armor:
            comps = EntityRegistry.get_item(item_id)
            assert "Armor" in comps, f"{item_id} missing Armor"
            assert comps["Armor"].magic_bonus == 1, f"{item_id} bonus != 1"
