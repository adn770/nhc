"""Tests for the item price table."""

import pytest

from nhc.entities.registry import EntityRegistry
from nhc.rules.prices import ITEM_PRICES, buy_price, sell_price


@pytest.fixture(autouse=True)
def _discover():
    EntityRegistry.discover_all()


class TestPriceTable:
    """Every registered item must have a price."""

    def test_all_items_have_prices(self):
        missing = []
        for item_id in EntityRegistry.list_items():
            if item_id not in ITEM_PRICES:
                missing.append(item_id)
        assert not missing, f"Items without prices: {missing}"

    def test_all_prices_positive(self):
        for item_id, price in ITEM_PRICES.items():
            assert price > 0, f"{item_id} has non-positive price {price}"


class TestBuyPrice:
    def test_known_item(self):
        assert buy_price("sword") == 10

    def test_unknown_item_returns_fallback(self):
        assert buy_price("nonexistent_item") == 5


class TestSellPrice:
    def test_half_of_buy(self):
        assert sell_price("sword") == 5

    def test_minimum_one(self):
        assert sell_price("gold") == 1

    def test_sell_always_half_buy_min_one(self):
        for item_id, price in ITEM_PRICES.items():
            expected = max(1, price // 2)
            assert sell_price(item_id) == expected, (
                f"{item_id}: expected {expected}, got {sell_price(item_id)}"
            )
