"""Tests for temple priest interaction and on-the-spot services."""

from __future__ import annotations

import pytest

from nhc.core.actions._temple import (
    BLESS_DURATION,
    TempleInteractAction,
    TempleServiceAction,
)
from nhc.core.ecs import World
from nhc.core.events import MessageEvent, TempleMenuEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Cursed,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    ShopInventory,
    Stats,
    StatusEffect,
    TempleServices,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.rules.prices import temple_service_price


@pytest.fixture(autouse=True)
def _setup():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_level(depth=2, width=10, height=10):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    return Level(
        id="t", name="T", depth=depth,
        width=width, height=height, tiles=tiles,
    )


def _make_player(world, x=5, y=5, gold=500, hp=10, max_hp=10):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=hp, maximum=max_hp),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(gold=gold),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_priest(world, x=6, y=5, services=None, stock=None):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="idle", morale=5, faction="human"),
        "Health": Health(current=12, maximum=12),
        "Description": Description(name="Priest"),
        "TempleServices": TempleServices(
            services=services or ["heal", "remove_curse", "bless"],
        ),
        "ShopInventory": ShopInventory(stock=stock or ["holy_water"]),
        "Renderable": Renderable(glyph="@", color="bright_white"),
    })


# ── Priest factory ──────────────────────────────────────────────────


class TestPriestFactory:
    def test_priest_registered(self):
        comps = EntityRegistry.get_creature("priest")
        assert "Renderable" in comps
        assert comps["Renderable"].glyph == "@"
        assert comps["AI"].faction == "human"
        assert comps["AI"].behavior == "idle"


# ── Interaction ──────────────────────────────────────────────────────


class TestTempleInteract:
    @pytest.mark.asyncio
    async def test_opens_temple_menu(self):
        world = World()
        level = _make_level()
        p = _make_player(world)
        priest = _make_priest(world)
        action = TempleInteractAction(actor=p, priest=priest)
        assert await action.validate(world, level)
        evs = await action.execute(world, level)
        assert len(evs) == 1
        assert isinstance(evs[0], TempleMenuEvent)
        assert evs[0].priest == priest

    @pytest.mark.asyncio
    async def test_fails_when_not_adjacent(self):
        world = World()
        level = _make_level()
        p = _make_player(world, x=1, y=1)
        priest = _make_priest(world, x=8, y=8)
        action = TempleInteractAction(actor=p, priest=priest)
        assert not await action.validate(world, level)


# ── Heal service ─────────────────────────────────────────────────────


class TestHealService:
    @pytest.mark.asyncio
    async def test_heal_restores_full_hp_and_deducts_gold(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world, gold=200, hp=3, max_hp=10)
        priest = _make_priest(world)
        price = temple_service_price("heal", level.depth)

        action = TempleServiceAction(
            actor=p, priest=priest, service_id="heal",
        )
        assert await action.validate(world, level)
        evs = await action.execute(world, level)

        health = world.get_component(p, "Health")
        player = world.get_component(p, "Player")
        assert health.current == health.maximum
        assert player.gold == 200 - price
        assert any(isinstance(e, MessageEvent) for e in evs)

    @pytest.mark.asyncio
    async def test_heal_blocked_when_full_hp(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world, hp=10, max_hp=10)
        priest = _make_priest(world)
        action = TempleServiceAction(
            actor=p, priest=priest, service_id="heal",
        )
        assert not await action.validate(world, level)
        assert action.fail_reason == "already_full_hp"

    @pytest.mark.asyncio
    async def test_heal_blocked_when_poor(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world, gold=0, hp=1, max_hp=10)
        priest = _make_priest(world)
        action = TempleServiceAction(
            actor=p, priest=priest, service_id="heal",
        )
        assert not await action.validate(world, level)
        assert action.fail_reason == "cannot_afford"


# ── Remove curse service ─────────────────────────────────────────────


class TestRemoveCurseService:
    @pytest.mark.asyncio
    async def test_removes_cursed_component(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world, gold=500)
        world.add_component(p, "Cursed", Cursed())
        priest = _make_priest(world)

        action = TempleServiceAction(
            actor=p, priest=priest, service_id="remove_curse",
        )
        assert await action.validate(world, level)
        await action.execute(world, level)
        assert not world.has_component(p, "Cursed")

    @pytest.mark.asyncio
    async def test_blocked_when_no_curse(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world)
        priest = _make_priest(world)
        action = TempleServiceAction(
            actor=p, priest=priest, service_id="remove_curse",
        )
        assert not await action.validate(world, level)
        assert action.fail_reason == "no_curse"


# ── Bless service ────────────────────────────────────────────────────


class TestBlessService:
    @pytest.mark.asyncio
    async def test_bless_applies_status(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world, gold=500)
        priest = _make_priest(world)

        action = TempleServiceAction(
            actor=p, priest=priest, service_id="bless",
        )
        assert await action.validate(world, level)
        await action.execute(world, level)
        status = world.get_component(p, "StatusEffect")
        assert status is not None
        assert status.blessed == BLESS_DURATION

    @pytest.mark.asyncio
    async def test_bless_blocked_when_already_blessed(self):
        world = World()
        level = _make_level(depth=2)
        p = _make_player(world, gold=500)
        world.add_component(
            p, "StatusEffect", StatusEffect(blessed=BLESS_DURATION),
        )
        priest = _make_priest(world)
        action = TempleServiceAction(
            actor=p, priest=priest, service_id="bless",
        )
        assert not await action.validate(world, level)
        assert action.fail_reason == "already_blessed"


# ── Pricing scales with depth ────────────────────────────────────────


class TestPricing:
    def test_prices_scale_with_depth(self):
        assert temple_service_price("heal", 1) == 20
        assert temple_service_price("heal", 5) == 100
        assert temple_service_price("remove_curse", 2) == 100
        assert temple_service_price("bless", 3) == 90
