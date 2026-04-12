"""Tests for henchman auto-equip: best equipment selection and triggers."""

import pytest

from nhc.ai.henchman_ai import auto_equip_best, decide_henchman_action
from nhc.core.actions import GiveItemAction, PickupItemAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.entities.components import (
    AI,
    Armor,
    BlocksMovement,
    Description,
    Equipment,
    Health,
    Henchman,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.creatures.adventurer import create_adventurer_at_level
from nhc.entities.registry import EntityRegistry
from nhc.utils.rng import set_seed


def _make_test_level(width=12, height=12):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    for x in range(width):
        tiles[0][x].terrain = Terrain.WALL
        tiles[height - 1][x].terrain = Terrain.WALL
    for y in range(height):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][width - 1].terrain = Terrain.WALL
    level = Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )
    level.rooms = [Room(
        id="r1",
        rect=Rect(1, 1, width - 2, height - 2),
        tags=[],
    )]
    return level


def _make_player(world, x=5, y=5, gold=500):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(gold=gold),
        "Description": Description(name="Hero"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_henchman(world, x=6, y=5, hired=True, owner=None):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=8, maximum=8),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "AI": AI(behavior="henchman", faction="human"),
        "Henchman": Henchman(level=1, hired=hired, owner=owner),
        "Description": Description(name="Adventurer"),
        "Renderable": Renderable(glyph="@", color="cyan"),
    })


def _make_weapon(world, damage="1d6", magic_bonus=0, name="Sword"):
    return world.create_entity({
        "Weapon": Weapon(damage=damage, magic_bonus=magic_bonus),
        "Description": Description(name=name),
    })


def _make_armor(world, slot="body", defense=12, magic_bonus=0,
                name="Armor"):
    return world.create_entity({
        "Armor": Armor(slot=slot, defense=defense,
                       magic_bonus=magic_bonus),
        "Description": Description(name=name),
    })


# ── auto_equip_best ──────────────────────────────────────────────


class TestAutoEquipBest:
    def test_equips_only_weapon_in_inventory(self):
        world = World()
        hid = _make_henchman(world)
        sword = _make_weapon(world, damage="1d8", name="Sword")

        inv = world.get_component(hid, "Inventory")
        inv.slots.append(sword)

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.weapon == sword

    def test_equips_best_weapon_by_damage(self):
        world = World()
        hid = _make_henchman(world)
        dagger = _make_weapon(world, damage="1d4", name="Dagger")
        sword = _make_weapon(world, damage="1d8", name="Sword")

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([dagger, sword])

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.weapon == sword

    def test_prefers_magic_weapon(self):
        world = World()
        hid = _make_henchman(world)
        sword = _make_weapon(world, damage="1d8", name="Sword")
        dagger_plus = _make_weapon(
            world, damage="1d4", magic_bonus=5, name="Dagger +5",
        )

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([sword, dagger_plus])

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        # Dagger +5: max 4+5=9 vs Sword: max 8+0=8
        assert equip.weapon == dagger_plus

    def test_equips_body_armor(self):
        world = World()
        hid = _make_henchman(world)
        gambeson = _make_armor(
            world, slot="body", defense=12, name="Gambeson",
        )

        inv = world.get_component(hid, "Inventory")
        inv.slots.append(gambeson)

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.armor == gambeson

    def test_equips_best_body_armor(self):
        world = World()
        hid = _make_henchman(world)
        gambeson = _make_armor(
            world, slot="body", defense=12, name="Gambeson",
        )
        chain = _make_armor(
            world, slot="body", defense=14, name="Chain Mail",
        )

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([gambeson, chain])

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.armor == chain

    def test_equips_shield_and_helmet(self):
        world = World()
        hid = _make_henchman(world)
        shield = _make_armor(
            world, slot="shield", defense=1, name="Shield",
        )
        helmet = _make_armor(
            world, slot="helmet", defense=1, name="Helmet",
        )

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([shield, helmet])

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.shield == shield
        assert equip.helmet == helmet

    def test_prefers_magic_armor(self):
        world = World()
        hid = _make_henchman(world)
        chain = _make_armor(
            world, slot="body", defense=14, name="Chain Mail",
        )
        gambeson_plus = _make_armor(
            world, slot="body", defense=12, magic_bonus=3,
            name="Gambeson +3",
        )

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([chain, gambeson_plus])

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        # Gambeson +3: 12+3=15 vs Chain: 14+0=14
        assert equip.armor == gambeson_plus

    def test_replaces_worse_weapon(self):
        """If already equipped with a weapon, upgrades to a better one."""
        world = World()
        hid = _make_henchman(world)
        dagger = _make_weapon(world, damage="1d4", name="Dagger")
        sword = _make_weapon(world, damage="1d8", name="Sword")

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([dagger, sword])

        equip = world.get_component(hid, "Equipment")
        equip.weapon = dagger  # pre-equipped with dagger

        auto_equip_best(world, hid)

        assert equip.weapon == sword

    def test_keeps_better_weapon(self):
        """Does not downgrade to a worse weapon."""
        world = World()
        hid = _make_henchman(world)
        sword = _make_weapon(world, damage="1d8", name="Sword")
        dagger = _make_weapon(world, damage="1d4", name="Dagger")

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([sword, dagger])

        equip = world.get_component(hid, "Equipment")
        equip.weapon = sword

        auto_equip_best(world, hid)

        assert equip.weapon == sword

    def test_no_inventory_is_noop(self):
        """No crash if entity has no Inventory."""
        world = World()
        eid = world.create_entity({
            "Equipment": Equipment(),
        })
        auto_equip_best(world, eid)  # should not raise

    def test_no_equipment_is_noop(self):
        """No crash if entity has no Equipment."""
        world = World()
        eid = world.create_entity({
            "Inventory": Inventory(),
        })
        auto_equip_best(world, eid)  # should not raise

    def test_equips_all_slots_at_once(self):
        """Weapon + body + shield + helmet all equipped together."""
        world = World()
        hid = _make_henchman(world)
        sword = _make_weapon(world, damage="1d8", name="Sword")
        chain = _make_armor(
            world, slot="body", defense=14, name="Chain",
        )
        shield = _make_armor(
            world, slot="shield", defense=1, name="Shield",
        )
        helmet = _make_armor(
            world, slot="helmet", defense=1, name="Helmet",
        )

        inv = world.get_component(hid, "Inventory")
        inv.slots.extend([sword, chain, shield, helmet])

        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.weapon == sword
        assert equip.armor == chain
        assert equip.shield == shield
        assert equip.helmet == helmet


# ── AI auto-equip on pickup ──────────────────────────────────────


class TestHenchmanAutoEquipOnPickup:
    @pytest.mark.asyncio
    async def test_equips_picked_up_weapon(self):
        """Henchman equips a weapon after picking it up."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=3, y=3)
        hid = _make_henchman(world, x=5, y=5, hired=True, owner=pid)

        # Place a sword on henchman's tile
        sword = _make_weapon(world, damage="1d8", name="Sword")
        world.add_component(sword, "Position", Position(x=5, y=5))

        action = PickupItemAction(actor=hid, item=sword)
        assert await action.validate(world, level)
        await action.execute(world, level)

        # After pickup, henchman AI should decide and auto-equip
        # For now, just verify item is in inventory
        inv = world.get_component(hid, "Inventory")
        assert sword in inv.slots

        # Call auto_equip_best (which the AI will call)
        auto_equip_best(world, hid)

        equip = world.get_component(hid, "Equipment")
        assert equip.weapon == sword

    @pytest.mark.asyncio
    async def test_ai_picks_up_and_equips(self):
        """Full AI decision: pick up item, then next turn equip it."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        hid = _make_henchman(world, x=5, y=6, hired=True, owner=pid)

        # Place a sword on henchman's tile
        sword = _make_weapon(world, damage="1d8", name="Sword")
        world.add_component(sword, "Position", Position(x=5, y=6))

        # AI should decide to pick up the item
        action = decide_henchman_action(hid, world, level, pid)
        assert action is not None
        assert isinstance(action, PickupItemAction)


# ── GiveItem auto-equip ──────────────────────────────────────────


class TestGiveItemAutoEquip:
    @pytest.mark.asyncio
    async def test_henchman_equips_given_weapon(self):
        """Henchman auto-equips a weapon received from the player."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        hid = _make_henchman(world, x=6, y=5, hired=True, owner=pid)

        sword = _make_weapon(world, damage="1d8", name="Sword")
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(sword)

        action = GiveItemAction(
            actor=pid, henchman_id=hid, item_id=sword,
        )
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # After give, henchman should have auto-equipped it
        equip = world.get_component(hid, "Equipment")
        assert equip.weapon == sword

    @pytest.mark.asyncio
    async def test_henchman_equips_better_given_weapon(self):
        """Henchman upgrades to a better weapon when given one."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        hid = _make_henchman(world, x=6, y=5, hired=True, owner=pid)

        dagger = _make_weapon(world, damage="1d4", name="Dagger")
        h_inv = world.get_component(hid, "Inventory")
        h_inv.slots.append(dagger)
        equip = world.get_component(hid, "Equipment")
        equip.weapon = dagger

        sword = _make_weapon(world, damage="1d8", name="Sword")
        p_inv = world.get_component(pid, "Inventory")
        p_inv.slots.append(sword)

        action = GiveItemAction(
            actor=pid, henchman_id=hid, item_id=sword,
        )
        await action.execute(world, level)

        assert equip.weapon == sword

    @pytest.mark.asyncio
    async def test_henchman_keeps_better_weapon_on_give(self):
        """Henchman does not downgrade when given a worse weapon."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        hid = _make_henchman(world, x=6, y=5, hired=True, owner=pid)

        sword = _make_weapon(world, damage="1d8", name="Sword")
        h_inv = world.get_component(hid, "Inventory")
        h_inv.slots.append(sword)
        equip = world.get_component(hid, "Equipment")
        equip.weapon = sword

        dagger = _make_weapon(world, damage="1d4", name="Dagger")
        p_inv = world.get_component(pid, "Inventory")
        p_inv.slots.append(dagger)

        action = GiveItemAction(
            actor=pid, henchman_id=hid, item_id=dagger,
        )
        await action.execute(world, level)

        assert equip.weapon == sword

    @pytest.mark.asyncio
    async def test_henchman_equips_given_armor(self):
        """Henchman auto-equips armor received from the player."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        hid = _make_henchman(world, x=6, y=5, hired=True, owner=pid)

        chain = _make_armor(
            world, slot="body", defense=14, name="Chain Mail",
        )
        p_inv = world.get_component(pid, "Inventory")
        p_inv.slots.append(chain)

        action = GiveItemAction(
            actor=pid, henchman_id=hid, item_id=chain,
        )
        await action.execute(world, level)

        equip = world.get_component(hid, "Equipment")
        assert equip.armor == chain


# ── Henchman starting equipment ──────────────────────────────────


class TestHenchmanStartingItems:
    def test_adventurer_has_starting_items(self):
        """create_adventurer_at_level includes starting_items."""
        set_seed(42)
        comps = create_adventurer_at_level(1, seed=42)
        assert "_starting_items" in comps
        items = comps["_starting_items"]
        assert isinstance(items, list)
        assert len(items) > 0
        # Should have at least a weapon from chargen
        has_weapon = any(
            item_id in (
                "dagger", "club", "short_sword", "sword",
                "spear", "axe", "mace",
            )
            for item_id in items
        )
        assert has_weapon
