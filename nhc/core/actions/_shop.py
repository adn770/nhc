"""Shop actions — buying and selling items from a merchant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import (
    _count_slots_used,
    _entity_name,
    _item_slot_cost,
)
from nhc.core.events import Event, MessageEvent, ShopMenuEvent
from nhc.i18n import t
from nhc.rules.prices import buy_price, sell_price

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


class ShopInteractAction(Action):
    """Open the shop menu when bumping a merchant."""

    def __init__(self, actor: int, merchant: int) -> None:
        super().__init__(actor)
        self.merchant = merchant

    async def validate(self, world: "World", level: "Level") -> bool:
        si = world.get_component(self.merchant, "ShopInventory")
        if not si:
            return False
        # Must be adjacent
        apos = world.get_component(self.actor, "Position")
        mpos = world.get_component(self.merchant, "Position")
        if not apos or not mpos:
            return False
        dx = abs(apos.x - mpos.x)
        dy = abs(apos.y - mpos.y)
        return dx <= 1 and dy <= 1

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return [ShopMenuEvent(merchant=self.merchant)]


class BuyAction(Action):
    """Buy an item from a merchant's stock."""

    def __init__(
        self, actor: int, merchant: int, item_id: str,
    ) -> None:
        super().__init__(actor)
        self.merchant = merchant
        self.item_id = item_id
        self._fail_reason = ""

    async def validate(self, world: "World", level: "Level") -> bool:
        si = world.get_component(self.merchant, "ShopInventory")
        if not si or self.item_id not in si.stock:
            self._fail_reason = "not_in_stock"
            return False

        player = world.get_component(self.actor, "Player")
        if not player:
            return False

        price = buy_price(self.item_id)
        if player.gold < price:
            self._fail_reason = "cannot_afford"
            return False

        inv = world.get_component(self.actor, "Inventory")
        if inv:
            from nhc.entities.registry import EntityRegistry
            components = EntityRegistry.get_item(self.item_id)
            # Estimate slot cost from the item's components
            slot_cost = 1
            if "Weapon" in components:
                slot_cost = components["Weapon"].slots
            elif "Armor" in components:
                slot_cost = components["Armor"].slots
            used = _count_slots_used(world, inv)
            if used + slot_cost > inv.max_slots:
                self._fail_reason = "inventory_full"
                return False

        return True

    @property
    def fail_reason(self) -> str:
        return self._fail_reason

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.entities.components import Position
        from nhc.entities.registry import EntityRegistry

        si = world.get_component(self.merchant, "ShopInventory")
        player = world.get_component(self.actor, "Player")
        price = buy_price(self.item_id)

        # Deduct gold
        player.gold -= price

        # Remove from merchant stock
        si.stock.remove(self.item_id)

        # Spawn the item entity and add to player inventory
        components = EntityRegistry.get_item(self.item_id)
        # No Position — goes straight to inventory
        item_eid = world.create_entity(components)

        inv = world.get_component(self.actor, "Inventory")
        if inv:
            inv.slots.append(item_eid)

        desc = world.get_component(item_eid, "Description")
        item_name = desc.name if desc else self.item_id

        return [MessageEvent(
            text=t("shop.bought", item=item_name, price=price),
        )]


class SellAction(Action):
    """Sell an item from the player's inventory to a merchant."""

    def __init__(
        self, actor: int, merchant: int, item_entity: int,
    ) -> None:
        super().__init__(actor)
        self.merchant = merchant
        self.item_entity = item_entity
        self._fail_reason = ""

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item_entity not in inv.slots:
            self._fail_reason = "not_in_inventory"
            return False

        # Cannot sell equipped items
        equip = world.get_component(self.actor, "Equipment")
        if equip:
            for slot in ("weapon", "armor", "shield", "helmet",
                         "ring_left", "ring_right"):
                if getattr(equip, slot) == self.item_entity:
                    self._fail_reason = "equipped"
                    return False

        return True

    @property
    def fail_reason(self) -> str:
        return self._fail_reason

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        inv = world.get_component(self.actor, "Inventory")
        player = world.get_component(self.actor, "Player")

        # Determine item_id for pricing
        desc = world.get_component(self.item_entity, "Description")
        item_name = desc.name if desc else "item"

        # Try to find the registry ID from the entity components
        item_id = self._resolve_item_id(world, self.item_entity)
        price = sell_price(item_id)

        # Add gold
        player.gold += price

        # Remove from inventory and destroy
        inv.slots.remove(self.item_entity)
        world.destroy_entity(self.item_entity)

        from nhc.core.events import ItemSold
        return [
            MessageEvent(
                text=t("shop.sold", item=item_name, price=price),
            ),
            ItemSold(entity=self.actor, item_id=item_id),
        ]

    @staticmethod
    def _resolve_item_id(world: "World", eid: int) -> str:
        """Look up the registry item_id for pricing."""
        reg = world.get_component(eid, "RegistryId")
        if reg:
            return reg.item_id
        return "gold"  # safe fallback
