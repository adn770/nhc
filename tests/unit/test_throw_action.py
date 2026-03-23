"""Tests for throwing potions at creatures."""
import pytest
from nhc.core.ecs import World
from nhc.core.actions import ThrowAction
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Consumable, Description, Equipment, Health, Inventory,
    Player, Position, Stats, StatusEffect, Undead,
)
from nhc.i18n import init as i18n_init


def _setup():
    i18n_init("en")
    w = World()
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    for row in tiles:
        for t in row:
            t.visible = True
    level = Level(id="t", name="T", depth=1, width=10, height=10,
                  tiles=tiles, rooms=[], corridors=[], entities=[])
    pid = w.create_entity({
        "Position": Position(x=5, y=5),
        "Stats": Stats(), "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12), "Player": Player(),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })
    mob = w.create_entity({
        "Position": Position(x=6, y=5),
        "AI": AI(behavior="aggressive_melee"),
        "Health": Health(current=8, maximum=8),
        "Description": Description(name="Goblin"),
    })
    return w, level, pid, mob


class TestThrowPotion:
    @pytest.mark.asyncio
    async def test_throw_fireball_deals_damage(self):
        w, l, pid, mob = _setup()
        pot = w.create_entity({
            "Consumable": Consumable(effect="fireball", dice="2d6"),
            "Description": Description(name="Fire Potion"),
        })
        w.get_component(pid, "Inventory").slots.append(pot)
        await ThrowAction(pid, pot, mob).execute(w, l)
        assert w.get_component(mob, "Health").current < 8

    @pytest.mark.asyncio
    async def test_throw_consumes_potion(self):
        w, l, pid, mob = _setup()
        pot = w.create_entity({
            "Consumable": Consumable(effect="fireball", dice="1d4"),
            "Description": Description(name="Potion"),
        })
        inv = w.get_component(pid, "Inventory")
        inv.slots.append(pot)
        await ThrowAction(pid, pot, mob).execute(w, l)
        assert pot not in inv.slots

    @pytest.mark.asyncio
    async def test_throw_frost_paralyzes(self):
        w, l, pid, mob = _setup()
        pot = w.create_entity({
            "Consumable": Consumable(effect="frost", dice="3"),
            "Description": Description(name="Frost Potion"),
        })
        w.get_component(pid, "Inventory").slots.append(pot)
        await ThrowAction(pid, pot, mob).execute(w, l)
        status = w.get_component(mob, "StatusEffect")
        assert status is not None
        assert status.paralyzed == 3

    @pytest.mark.asyncio
    async def test_throw_sleep_on_undead_no_effect(self):
        w, l, pid, mob = _setup()
        w.add_component(mob, "Undead", Undead())
        pot = w.create_entity({
            "Consumable": Consumable(effect="sleep", dice="2d8"),
            "Description": Description(name="Sleep Potion"),
        })
        w.get_component(pid, "Inventory").slots.append(pot)
        await ThrowAction(pid, pot, mob).execute(w, l)
        status = w.get_component(mob, "StatusEffect")
        # Undead immune to sleep
        assert status is None or status.sleeping == 0

    @pytest.mark.asyncio
    async def test_throw_validates_target_visible(self):
        w, l, pid, mob = _setup()
        # Make mob's tile not visible
        l.tiles[5][6].visible = False
        pot = w.create_entity({
            "Consumable": Consumable(effect="fireball", dice="1d4"),
            "Description": Description(name="Potion"),
        })
        w.get_component(pid, "Inventory").slots.append(pot)
        assert not await ThrowAction(pid, pot, mob).validate(w, l)
