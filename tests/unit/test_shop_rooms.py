"""Tests for shop room generation."""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.room_types import SHOP_STOCK
from nhc.entities.registry import EntityRegistry


def _find_tagged(level: Level, tag: str):
    return [r for r in level.rooms if tag in r.tags]


def _entities_in_room(level: Level, room):
    inside = set(room.floor_tiles())
    return [e for e in level.entities if (e.x, e.y) in inside]


class TestShopRoomAssignment:
    """Shop rooms appear in dungeons and contain a merchant."""

    def test_shops_appear_across_seeds(self):
        """Shops should appear in a reasonable fraction of dungeons."""
        with_shop = 0
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            if _find_tagged(level, "shop"):
                with_shop += 1
        assert with_shop >= 5, (
            f"Only {with_shop}/200 seeds produced a shop"
        )

    def test_max_one_shop_per_level(self):
        """At most 1 shop room per dungeon level."""
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            shops = _find_tagged(level, "shop")
            assert len(shops) <= 1, (
                f"Seed {seed}: found {len(shops)} shops"
            )


class TestShopContents:
    """Shop rooms contain exactly one merchant with stock."""

    def _find_shop_level(self):
        """Return a level with at least one shop room."""
        for seed in range(500):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            shops = _find_tagged(level, "shop")
            if shops:
                return level, shops[0]
        pytest.skip("No shop found in 500 seeds")

    def test_shop_has_merchant(self):
        level, shop = self._find_shop_level()
        entities = _entities_in_room(level, shop)
        merchants = [
            e for e in entities
            if e.entity_type == "creature" and e.entity_id == "merchant"
        ]
        assert len(merchants) == 1

    def test_merchant_has_shop_stock(self):
        level, shop = self._find_shop_level()
        entities = _entities_in_room(level, shop)
        merchants = [
            e for e in entities
            if e.entity_type == "creature" and e.entity_id == "merchant"
        ]
        assert len(merchants) == 1
        merchant = merchants[0]
        stock = merchant.extra.get("shop_stock")
        assert stock is not None
        assert len(stock) >= 1
        # All stock items should be registered items
        EntityRegistry.discover_all()
        registered = set(EntityRegistry.list_items())
        for item_id in stock:
            assert item_id in registered, (
                f"Stock item '{item_id}' not in registry"
            )

    def test_shop_stock_items_are_unique(self):
        level, shop = self._find_shop_level()
        entities = _entities_in_room(level, shop)
        merchant = next(
            e for e in entities
            if e.entity_type == "creature" and e.entity_id == "merchant"
        )
        stock = merchant.extra["shop_stock"]
        assert len(stock) == len(set(stock)), (
            f"Duplicate items in stock: {stock}"
        )


class TestPopulatorSkipsShop:
    """The standard populator should not place creatures in shops."""

    def test_no_extra_creatures_in_shop(self):
        level, shop = TestShopContents()._find_shop_level()
        entities = _entities_in_room(level, shop)
        creatures = [
            e for e in entities if e.entity_type == "creature"
        ]
        # Only the merchant, nothing from populate_level
        assert len(creatures) == 1
        assert creatures[0].entity_id == "merchant"
