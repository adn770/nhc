"""Tests for equip/unequip across all slot types."""
import pytest
from nhc.core.ecs import World
from nhc.core.actions import EquipAction, UnequipAction, DropAction
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    Armor, Description, Equipment, Health, Inventory, Player,
    Position, Renderable, Ring, Stats, Weapon,
)
from nhc.i18n import init as i18n_init


def _world():
    i18n_init("en")
    world = World()
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    level = Level(id="t", name="T", depth=1, width=10, height=10,
                  tiles=tiles, rooms=[], corridors=[], entities=[])
    pid = world.create_entity({
        "Position": Position(x=5, y=5),
        "Stats": Stats(strength=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })
    return world, level, pid


class TestEquipWeapon:
    @pytest.mark.asyncio
    async def test_equip_weapon(self):
        w, l, pid = _world()
        sword = w.create_entity({"Weapon": Weapon(damage="1d8"),
                                  "Description": Description(name="Sword")})
        w.get_component(pid, "Inventory").slots.append(sword)
        action = EquipAction(pid, sword)
        assert await action.validate(w, l)
        await action.execute(w, l)
        assert w.get_component(pid, "Equipment").weapon == sword

    @pytest.mark.asyncio
    async def test_swap_weapon(self):
        w, l, pid = _world()
        s1 = w.create_entity({"Weapon": Weapon(damage="1d6"),
                               "Description": Description(name="Dagger")})
        s2 = w.create_entity({"Weapon": Weapon(damage="1d8"),
                               "Description": Description(name="Sword")})
        inv = w.get_component(pid, "Inventory")
        inv.slots.extend([s1, s2])
        await EquipAction(pid, s1).execute(w, l)
        assert w.get_component(pid, "Equipment").weapon == s1
        await EquipAction(pid, s2).execute(w, l)
        assert w.get_component(pid, "Equipment").weapon == s2


class TestEquipArmor:
    @pytest.mark.asyncio
    async def test_equip_body_armor(self):
        w, l, pid = _world()
        arm = w.create_entity({"Armor": Armor(slot="body", defense=12),
                                "Description": Description(name="Gambeson")})
        w.get_component(pid, "Inventory").slots.append(arm)
        await EquipAction(pid, arm).execute(w, l)
        assert w.get_component(pid, "Equipment").armor == arm

    @pytest.mark.asyncio
    async def test_equip_shield(self):
        w, l, pid = _world()
        sh = w.create_entity({"Armor": Armor(slot="shield", defense=1),
                               "Description": Description(name="Shield")})
        w.get_component(pid, "Inventory").slots.append(sh)
        await EquipAction(pid, sh).execute(w, l)
        assert w.get_component(pid, "Equipment").shield == sh

    @pytest.mark.asyncio
    async def test_equip_helmet(self):
        w, l, pid = _world()
        h = w.create_entity({"Armor": Armor(slot="helmet", defense=1),
                              "Description": Description(name="Helmet")})
        w.get_component(pid, "Inventory").slots.append(h)
        await EquipAction(pid, h).execute(w, l)
        assert w.get_component(pid, "Equipment").helmet == h


class TestEquipRing:
    @pytest.mark.asyncio
    async def test_equip_ring_left(self):
        w, l, pid = _world()
        r = w.create_entity({"Ring": Ring(effect="mending"),
                              "Description": Description(name="Ring")})
        w.get_component(pid, "Inventory").slots.append(r)
        await EquipAction(pid, r).execute(w, l)
        assert w.get_component(pid, "Equipment").ring_left == r

    @pytest.mark.asyncio
    async def test_equip_two_rings(self):
        w, l, pid = _world()
        r1 = w.create_entity({"Ring": Ring(effect="mending"),
                               "Description": Description(name="Ring1")})
        r2 = w.create_entity({"Ring": Ring(effect="protection"),
                               "Description": Description(name="Ring2")})
        inv = w.get_component(pid, "Inventory")
        inv.slots.extend([r1, r2])
        await EquipAction(pid, r1).execute(w, l)
        await EquipAction(pid, r2).execute(w, l)
        equip = w.get_component(pid, "Equipment")
        assert equip.ring_left == r1
        assert equip.ring_right == r2

    @pytest.mark.asyncio
    async def test_equip_third_ring_swaps_left(self):
        w, l, pid = _world()
        r1 = w.create_entity({"Ring": Ring(effect="a"),
                               "Description": Description(name="R1")})
        r2 = w.create_entity({"Ring": Ring(effect="b"),
                               "Description": Description(name="R2")})
        r3 = w.create_entity({"Ring": Ring(effect="c"),
                               "Description": Description(name="R3")})
        inv = w.get_component(pid, "Inventory")
        inv.slots.extend([r1, r2, r3])
        await EquipAction(pid, r1).execute(w, l)
        await EquipAction(pid, r2).execute(w, l)
        await EquipAction(pid, r3).execute(w, l)
        equip = w.get_component(pid, "Equipment")
        assert equip.ring_left == r3
        assert equip.ring_right == r2


class TestUnequip:
    @pytest.mark.asyncio
    async def test_unequip_weapon(self):
        w, l, pid = _world()
        s = w.create_entity({"Weapon": Weapon(damage="1d8"),
                              "Description": Description(name="Sword")})
        w.get_component(pid, "Inventory").slots.append(s)
        w.get_component(pid, "Equipment").weapon = s
        await UnequipAction(pid, s).execute(w, l)
        assert w.get_component(pid, "Equipment").weapon is None

    @pytest.mark.asyncio
    async def test_unequip_ring(self):
        w, l, pid = _world()
        r = w.create_entity({"Ring": Ring(effect="mending"),
                              "Description": Description(name="Ring")})
        w.get_component(pid, "Inventory").slots.append(r)
        w.get_component(pid, "Equipment").ring_left = r
        await UnequipAction(pid, r).execute(w, l)
        assert w.get_component(pid, "Equipment").ring_left is None

    @pytest.mark.asyncio
    async def test_unequip_validates_equipped(self):
        w, l, pid = _world()
        s = w.create_entity({"Weapon": Weapon(damage="1d8"),
                              "Description": Description(name="Sword")})
        w.get_component(pid, "Inventory").slots.append(s)
        # Not equipped — validate should fail
        assert not await UnequipAction(pid, s).validate(w, l)


class TestDrop:
    @pytest.mark.asyncio
    async def test_drop_returns_to_map(self):
        w, l, pid = _world()
        s = w.create_entity({"Description": Description(name="Sword")})
        w.get_component(pid, "Inventory").slots.append(s)
        await DropAction(pid, s).execute(w, l)
        assert s not in w.get_component(pid, "Inventory").slots
        pos = w.get_component(s, "Position")
        assert pos is not None
        assert pos.x == 5 and pos.y == 5

    @pytest.mark.asyncio
    async def test_drop_unequips(self):
        w, l, pid = _world()
        s = w.create_entity({"Weapon": Weapon(damage="1d8"),
                              "Description": Description(name="Sword")})
        inv = w.get_component(pid, "Inventory")
        inv.slots.append(s)
        w.get_component(pid, "Equipment").weapon = s
        await DropAction(pid, s).execute(w, l)
        assert w.get_component(pid, "Equipment").weapon is None
