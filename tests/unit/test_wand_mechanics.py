"""Tests for wand charge, recharge, and zap mechanics."""
import pytest
from nhc.core.ecs import World
from nhc.core.actions import ZapAction
from nhc.core.events import CreatureDied
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Description, Equipment, Health, Inventory, Player,
    Position, Stats, StatusEffect, Wand,
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
        "Stats": Stats(strength=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
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


class TestZapAction:
    @pytest.mark.asyncio
    async def test_zap_decrements_charge(self):
        w, l, pid, mob = _setup()
        wand = w.create_entity({
            "Wand": Wand(effect="magic_missile", charges=5, max_charges=10),
            "Description": Description(name="Wand"),
        })
        w.get_component(pid, "Inventory").slots.append(wand)
        action = ZapAction(pid, wand, mob)
        assert await action.validate(w, l)
        await action.execute(w, l)
        assert w.get_component(wand, "Wand").charges == 4

    @pytest.mark.asyncio
    async def test_zap_no_charges_invalid(self):
        w, l, pid, mob = _setup()
        wand = w.create_entity({
            "Wand": Wand(effect="magic_missile", charges=0, max_charges=10),
            "Description": Description(name="Wand"),
        })
        w.get_component(pid, "Inventory").slots.append(wand)
        assert not await ZapAction(pid, wand, mob).validate(w, l)

    @pytest.mark.asyncio
    async def test_zap_magic_missile_deals_damage(self):
        w, l, pid, mob = _setup()
        wand = w.create_entity({
            "Wand": Wand(effect="magic_missile", charges=3, max_charges=10),
            "Description": Description(name="Wand"),
        })
        w.get_component(pid, "Inventory").slots.append(wand)
        await ZapAction(pid, wand, mob).execute(w, l)
        hp = w.get_component(mob, "Health")
        assert hp.current < 8

    @pytest.mark.asyncio
    async def test_zap_poison_applies_poison(self):
        w, l, pid, mob = _setup()
        wand = w.create_entity({
            "Wand": Wand(effect="poison", charges=3, max_charges=10),
            "Description": Description(name="Wand"),
        })
        w.get_component(pid, "Inventory").slots.append(wand)
        await ZapAction(pid, wand, mob).execute(w, l)
        poison = w.get_component(mob, "Poison")
        assert poison is not None
        assert poison.turns_remaining == 5

    @pytest.mark.asyncio
    async def test_zap_amok_confuses(self):
        w, l, pid, mob = _setup()
        wand = w.create_entity({
            "Wand": Wand(effect="amok", charges=3, max_charges=10),
            "Description": Description(name="Wand"),
        })
        w.get_component(pid, "Inventory").slots.append(wand)
        await ZapAction(pid, wand, mob).execute(w, l)
        status = w.get_component(mob, "StatusEffect")
        assert status is not None
        assert status.confused == 6

    @pytest.mark.asyncio
    async def test_zap_slowness_webs(self):
        w, l, pid, mob = _setup()
        wand = w.create_entity({
            "Wand": Wand(effect="slowness", charges=3, max_charges=10),
            "Description": Description(name="Wand"),
        })
        w.get_component(pid, "Inventory").slots.append(wand)
        await ZapAction(pid, wand, mob).execute(w, l)
        status = w.get_component(mob, "StatusEffect")
        assert status is not None
        assert status.webbed == 8


class TestWandRecharge:
    def test_wand_initial_charges(self):
        """Wand factories produce 2d10 charges (2-20 range)."""
        from nhc.entities.registry import EntityRegistry
        EntityRegistry.discover_all()
        from nhc.utils.rng import set_seed
        set_seed(42)
        comps = EntityRegistry.get_item("wand_firebolt")
        wand = comps["Wand"]
        assert 2 <= wand.charges <= 20
        assert wand.charges == wand.max_charges
