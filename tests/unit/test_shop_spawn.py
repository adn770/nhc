"""Tests for merchant entity spawning with shop stock."""

from __future__ import annotations

import pytest

from nhc.core.ecs import World
from nhc.dungeon.model import EntityPlacement, Level, Terrain, Tile
from nhc.entities.components import (
    AI, BlocksMovement, Position, ShopInventory,
)
from nhc.entities.registry import EntityRegistry


@pytest.fixture(autouse=True)
def _discover():
    EntityRegistry.discover_all()


def _make_level(width=10, height=10):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    return Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )


def _spawn_entities(world: World, level: Level) -> None:
    """Replicate the spawn logic from Game._spawn_level_entities."""
    for placement in level.entities:
        if placement.entity_type == "creature":
            components = EntityRegistry.get_creature(placement.entity_id)
            components["BlocksMovement"] = BlocksMovement()
            if placement.extra.get("shop_stock"):
                components["ShopInventory"] = ShopInventory(
                    stock=list(placement.extra["shop_stock"]),
                )
        elif placement.entity_type == "item":
            components = EntityRegistry.get_item(placement.entity_id)
        else:
            continue
        components["Position"] = Position(
            x=placement.x, y=placement.y, level_id=level.id,
        )
        world.create_entity(components)


class TestMerchantSpawnWithStock:
    def test_merchant_gets_shop_inventory(self):
        world = World()
        level = _make_level()
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id="merchant",
            x=5, y=5, extra={"shop_stock": ["sword", "potion_healing"]},
        ))
        _spawn_entities(world, level)

        merchants = [
            (eid, si)
            for eid, si in world.query("ShopInventory")
        ]
        assert len(merchants) == 1
        _, si = merchants[0]
        assert si.stock == ["sword", "potion_healing"]

    def test_merchant_without_stock_has_no_shop_inventory(self):
        world = World()
        level = _make_level()
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id="merchant",
            x=5, y=5,
        ))
        _spawn_entities(world, level)

        merchants = [
            (eid, si)
            for eid, si in world.query("ShopInventory")
        ]
        assert len(merchants) == 0

    def test_merchant_keeps_ai_and_blocks_movement(self):
        world = World()
        level = _make_level()
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id="merchant",
            x=5, y=5, extra={"shop_stock": ["dagger"]},
        ))
        _spawn_entities(world, level)

        for eid, si in world.query("ShopInventory"):
            assert world.has_component(eid, "AI")
            assert world.has_component(eid, "BlocksMovement")
