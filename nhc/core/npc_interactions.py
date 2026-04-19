"""NPC interaction flows: shop, temple, and henchman menus.

Extracted from Game to keep the god-object under control.
Each method receives an entity ID and drives the async
buy/sell/hire menu loop using the Game's shared state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions import _count_slots_used, _entity_name, _item_slot_cost
from nhc.core.events import MessageEvent
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import WorldType
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.game import Game


class NpcInteractions:
    """Drives NPC dialog menus on behalf of the Game."""

    def __init__(self, game: Game) -> None:
        self.game = game

    # ── Convenience accessors ──────────────────────────────────────

    @property
    def world(self):
        return self.game.world

    @property
    def level(self):
        return self.game.level

    @property
    def player_id(self):
        return self.game.player_id

    @property
    def renderer(self):
        return self.game.renderer

    @property
    def _knowledge(self):
        return self.game._knowledge

    # ── Shop ───────────────────────────────────────────────────────

    async def shop_interaction(self, merchant_id: int) -> None:
        """Run the buy/sell/leave menu loop for a merchant."""
        from nhc.core.actions._shop import BuyAction, SellAction
        from nhc.rules.prices import buy_price, sell_price

        si = self.world.get_component(merchant_id, "ShopInventory")
        if not si:
            return

        _BUY = -1
        _SELL = -2

        while True:
            options: list[tuple[int, str]] = [
                (_BUY, t("shop.buy")),
                (_SELL, t("shop.sell")),
            ]
            choice = self.renderer.show_selection_menu(
                t("shop.welcome"), options,
            )
            if choice is None:
                break

            if choice == _BUY:
                if not si.stock:
                    self.renderer.add_message(t("shop.empty_stock"))
                    continue
                items: list[tuple[int, str]] = []
                for idx, item_id in enumerate(si.stock):
                    # Show appearance name for unidentified items
                    if (self._knowledge
                            and self._knowledge.is_identifiable(item_id)
                            and not self._knowledge.is_identified(item_id)):
                        name = self._knowledge.display_name(item_id)
                    else:
                        comps = EntityRegistry.get_item(item_id)
                        desc = comps.get("Description")
                        name = desc.name if desc else item_id
                    price = buy_price(item_id)
                    items.append((idx, f"{name} ({price}g)"))
                selected = self.renderer.show_selection_menu(
                    t("shop.buy"), items,
                )
                if selected is None:
                    continue
                # selected is the index into si.stock
                if selected < 0 or selected >= len(si.stock):
                    continue
                item_id = si.stock[selected]
                action = BuyAction(
                    actor=self.player_id,
                    merchant=merchant_id,
                    item_id=item_id,
                )
                if await action.validate(self.world, self.level):
                    events = await action.execute(self.world, self.level)
                    for ev in events:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                    # Disguise unidentified potions/scrolls
                    inv = self.world.get_component(
                        self.player_id, "Inventory",
                    )
                    if inv and inv.slots:
                        new_eid = inv.slots[-1]
                        new_comps = {
                            "Description": self.world.get_component(
                                new_eid, "Description"),
                            "Renderable": self.world.get_component(
                                new_eid, "Renderable"),
                        }
                        self.game._disguise_potion(new_comps, item_id)
                        if "_potion_id" in new_comps:
                            self.world.add_component(
                                new_eid, "_potion_id",
                                new_comps["_potion_id"],
                            )
                else:
                    reason = action.fail_reason
                    if reason == "cannot_afford":
                        self.renderer.add_message(
                            t("shop.cannot_afford",
                              price=buy_price(item_id)),
                        )
                    elif reason == "inventory_full":
                        self.renderer.add_message(
                            t("shop.inventory_full"),
                        )

            elif choice == _SELL:
                inv = self.world.get_component(
                    self.player_id, "Inventory",
                )
                if not inv or not inv.slots:
                    self.renderer.add_message(t("shop.nothing_to_sell"))
                    continue
                items = []
                for item_eid in inv.slots:
                    desc = self.world.get_component(item_eid, "Description")
                    reg = self.world.get_component(item_eid, "RegistryId")
                    name = desc.name if desc else "???"
                    item_id = reg.item_id if reg else "gold"
                    price = sell_price(item_id)
                    items.append((item_eid, f"{name} ({price}g)"))
                selected = self.renderer.show_selection_menu(
                    t("shop.sell"), items,
                )
                if selected is None:
                    continue
                action = SellAction(
                    actor=self.player_id,
                    merchant=merchant_id,
                    item_entity=selected,
                )
                if await action.validate(self.world, self.level):
                    events = await action.execute(self.world, self.level)
                    for ev in events:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                else:
                    reason = action.fail_reason
                    if reason == "equipped":
                        self.renderer.add_message(
                            t("shop.unequip_first"),
                        )

    # ── Temple ─────────────────────────────────────────────────────

    async def temple_interaction(self, priest_id: int) -> None:
        """Run the services + items menu loop for a priest."""
        from nhc.core.actions._shop import BuyAction
        from nhc.core.actions._temple import TempleServiceAction
        from nhc.rules.prices import buy_price, temple_service_price

        ts = self.world.get_component(priest_id, "TempleServices")
        if not ts:
            return

        _SERVICES = -1
        _GOODS = -2

        depth = self.level.depth

        while True:
            top: list[tuple[int, str]] = [
                (_SERVICES, t("temple.services")),
                (_GOODS, t("temple.goods")),
            ]
            choice = self.renderer.show_selection_menu(
                t("temple.welcome"), top,
            )
            if choice is None:
                break

            if choice == _SERVICES:
                svc_options: list[tuple[int, str]] = []
                for idx, sid in enumerate(ts.services):
                    price = temple_service_price(sid, depth)
                    label = t(f"temple.service.{sid}", price=price)
                    svc_options.append((idx, label))
                selected = self.renderer.show_selection_menu(
                    t("temple.services"), svc_options,
                )
                if selected is None or selected < 0 \
                        or selected >= len(ts.services):
                    continue
                sid = ts.services[selected]
                action = TempleServiceAction(
                    actor=self.player_id, priest=priest_id,
                    service_id=sid,
                )
                if await action.validate(self.world, self.level):
                    evs = await action.execute(self.world, self.level)
                    for ev in evs:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                else:
                    reason = action.fail_reason
                    msg_key = {
                        "cannot_afford": "temple.cannot_afford",
                        "no_curse": "temple.no_curse",
                        "already_full_hp": "temple.already_full_hp",
                        "already_blessed": "temple.already_blessed",
                    }.get(reason)
                    if msg_key:
                        if reason == "cannot_afford":
                            self.renderer.add_message(t(
                                msg_key,
                                price=temple_service_price(sid, depth),
                            ))
                        else:
                            self.renderer.add_message(t(msg_key))

            elif choice == _GOODS:
                si = self.world.get_component(priest_id, "ShopInventory")
                if not si or not si.stock:
                    self.renderer.add_message(t("temple.empty_stock"))
                    continue
                items: list[tuple[int, str]] = []
                for idx, item_id in enumerate(si.stock):
                    if (self._knowledge
                            and self._knowledge.is_identifiable(item_id)
                            and not self._knowledge.is_identified(item_id)):
                        name = self._knowledge.display_name(item_id)
                    else:
                        comps = EntityRegistry.get_item(item_id)
                        desc = comps.get("Description")
                        name = desc.name if desc else item_id
                    price = buy_price(item_id)
                    items.append((idx, f"{name} ({price}g)"))
                selected = self.renderer.show_selection_menu(
                    t("temple.goods"), items,
                )
                if selected is None or selected < 0 \
                        or selected >= len(si.stock):
                    continue
                item_id = si.stock[selected]
                action = BuyAction(
                    actor=self.player_id,
                    merchant=priest_id,
                    item_id=item_id,
                )
                if await action.validate(self.world, self.level):
                    evs = await action.execute(self.world, self.level)
                    for ev in evs:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                    inv = self.world.get_component(
                        self.player_id, "Inventory",
                    )
                    if inv and inv.slots:
                        new_eid = inv.slots[-1]
                        new_comps = {
                            "Description": self.world.get_component(
                                new_eid, "Description"),
                            "Renderable": self.world.get_component(
                                new_eid, "Renderable"),
                        }
                        self.game._disguise_potion(new_comps, item_id)
                        if "_potion_id" in new_comps:
                            self.world.add_component(
                                new_eid, "_potion_id",
                                new_comps["_potion_id"],
                            )
                else:
                    reason = action.fail_reason
                    if reason == "cannot_afford":
                        self.renderer.add_message(t(
                            "temple.cannot_afford",
                            price=buy_price(item_id),
                        ))
                    elif reason == "inventory_full":
                        self.renderer.add_message(t("shop.inventory_full"))

    # ── Henchman ───────────────────────────────────────────────────

    async def henchman_interaction(self, henchman_id: int) -> None:
        """Run the buy/sell/hire menu loop for an unhired henchman."""
        from nhc.core.actions._henchman import (
            HIRE_COST_PER_LEVEL,
            MAX_EXPEDITION,
            MAX_HENCHMEN,
            DismissAction,
            RecruitAction,
            _count_hired,
            get_hired_henchmen,
        )

        max_party = (
            MAX_EXPEDITION if self.game.world_type is WorldType.HEXCRAWL else MAX_HENCHMEN
        )
        from nhc.rules.prices import buy_price, sell_price

        hench = self.world.get_component(henchman_id, "Henchman")
        if not hench or hench.hired:
            return

        hench_name = _entity_name(self.world, henchman_id)
        hire_cost = HIRE_COST_PER_LEVEL * hench.level

        _BUY = -1
        _SELL = -2
        _HIRE = -3

        while True:
            options: list[tuple[int, str]] = [
                (_BUY, t("henchman.buy")),
                (_SELL, t("henchman.sell")),
                (_HIRE, t("henchman.hire", cost=hire_cost)),
            ]
            choice = self.renderer.show_selection_menu(
                t("henchman.welcome"), options,
            )
            if choice is None:
                break

            if choice == _BUY:
                # Buy from henchman's inventory
                h_inv = self.world.get_component(
                    henchman_id, "Inventory",
                )
                if not h_inv or not h_inv.slots:
                    self.renderer.add_message(
                        t("henchman.nothing_to_buy", name=hench_name),
                    )
                    continue

                # Build item list with prices
                items: list[tuple[int, str]] = []
                for item_eid in h_inv.slots:
                    desc = self.world.get_component(
                        item_eid, "Description",
                    )
                    reg = self.world.get_component(
                        item_eid, "RegistryId",
                    )
                    name = desc.name if desc else "???"
                    item_id = reg.item_id if reg else "gold"
                    price = buy_price(item_id)
                    items.append((item_eid, f"{name} ({price}g)"))

                selected = self.renderer.show_selection_menu(
                    t("henchman.buy"), items,
                )
                if selected is None:
                    continue

                # Validate and execute buy
                reg = self.world.get_component(selected, "RegistryId")
                item_id = reg.item_id if reg else "gold"
                price = buy_price(item_id)
                player = self.world.get_component(
                    self.player_id, "Player",
                )

                if player.gold < price:
                    self.renderer.add_message(
                        t("henchman.cannot_afford_buy", price=price),
                    )
                    continue

                # Check player inventory space
                p_inv = self.world.get_component(
                    self.player_id, "Inventory",
                )
                if p_inv:
                    used = _count_slots_used(self.world, p_inv)
                    cost = _item_slot_cost(self.world, selected)
                    if used + cost > p_inv.max_slots:
                        self.renderer.add_message(
                            t("shop.inventory_full"),
                        )
                        continue

                # Transfer item
                h_inv.slots.remove(selected)
                p_inv.slots.append(selected)
                player.gold -= price
                hench.gold += price

                # Unequip from henchman if equipped
                h_equip = self.world.get_component(
                    henchman_id, "Equipment",
                )
                if h_equip:
                    for slot in ("weapon", "armor", "shield",
                                 "helmet", "ring_left", "ring_right"):
                        if getattr(h_equip, slot) == selected:
                            setattr(h_equip, slot, None)

                # Henchman re-evaluates equipment
                from nhc.ai.henchman_ai import auto_equip_best
                auto_equip_best(self.world, henchman_id)

                desc = self.world.get_component(selected, "Description")
                item_name = desc.name if desc else "item"
                self.renderer.add_message(
                    t("henchman.bought",
                      item=item_name, name=hench_name, price=price),
                )

            elif choice == _SELL:
                # Sell from player's inventory to henchman
                p_inv = self.world.get_component(
                    self.player_id, "Inventory",
                )
                if not p_inv or not p_inv.slots:
                    self.renderer.add_message(
                        t("shop.nothing_to_sell"),
                    )
                    continue

                items = []
                for item_eid in p_inv.slots:
                    desc = self.world.get_component(
                        item_eid, "Description",
                    )
                    reg = self.world.get_component(
                        item_eid, "RegistryId",
                    )
                    name = desc.name if desc else "???"
                    item_id = reg.item_id if reg else "gold"
                    price = sell_price(item_id)
                    items.append((item_eid, f"{name} ({price}g)"))

                selected = self.renderer.show_selection_menu(
                    t("henchman.sell"), items,
                )
                if selected is None:
                    continue

                # Cannot sell equipped items
                p_equip = self.world.get_component(
                    self.player_id, "Equipment",
                )
                if p_equip:
                    is_equipped = False
                    for slot in ("weapon", "armor", "shield",
                                 "helmet", "ring_left", "ring_right"):
                        if getattr(p_equip, slot) == selected:
                            is_equipped = True
                            break
                    if is_equipped:
                        self.renderer.add_message(
                            t("shop.unequip_first"),
                        )
                        continue

                reg = self.world.get_component(selected, "RegistryId")
                item_id = reg.item_id if reg else "gold"
                price = sell_price(item_id)

                # Check henchman can afford it
                if hench.gold < price:
                    self.renderer.add_message(
                        t("henchman.hench_cannot_afford",
                          name=hench_name),
                    )
                    continue

                # Check henchman inventory space
                h_inv = self.world.get_component(
                    henchman_id, "Inventory",
                )
                if h_inv:
                    used = _count_slots_used(self.world, h_inv)
                    cost = _item_slot_cost(self.world, selected)
                    if used + cost > h_inv.max_slots:
                        self.renderer.add_message(
                            t("henchman.give_full", name=hench_name),
                        )
                        continue

                # Transfer item
                p_inv.slots.remove(selected)
                h_inv.slots.append(selected)
                player = self.world.get_component(
                    self.player_id, "Player",
                )
                player.gold += price
                hench.gold -= price

                # Henchman auto-equips best gear
                from nhc.ai.henchman_ai import auto_equip_best
                auto_equip_best(self.world, henchman_id)

                desc = self.world.get_component(selected, "Description")
                item_name = desc.name if desc else "item"
                self.renderer.add_message(
                    t("henchman.sold",
                      item=item_name, name=hench_name, price=price),
                )

            elif choice == _HIRE:
                player = self.world.get_component(
                    self.player_id, "Player",
                )
                if player.gold < hire_cost:
                    self.renderer.add_message(
                        t("henchman.no_gold",
                          name=hench_name, cost=hire_cost),
                    )
                    continue

                # If party is full, offer to dismiss one.
                hired_count = _count_hired(
                    self.world, self.player_id,
                )
                if hired_count >= max_party:
                    hired_ids = get_hired_henchmen(
                        self.world, self.player_id,
                    )
                    dismiss_opts: list[tuple[int, str]] = []
                    for hid in hired_ids:
                        name = _entity_name(self.world, hid)
                        dismiss_opts.append((hid, name))

                    to_dismiss = self.renderer.show_selection_menu(
                        t("henchman.dismiss_to_hire"),
                        dismiss_opts,
                    )
                    if to_dismiss is None:
                        continue

                    # Dismiss the selected henchman
                    dismiss = DismissAction(
                        actor=self.player_id,
                        henchman_id=to_dismiss,
                    )
                    if await dismiss.validate(
                        self.world, self.level,
                    ):
                        events = await dismiss.execute(
                            self.world, self.level,
                        )
                        for ev in events:
                            if isinstance(ev, MessageEvent):
                                self.renderer.add_message(ev.text)

                # Now recruit
                recruit = RecruitAction(
                    actor=self.player_id,
                    target=henchman_id,
                    max_party=max_party,
                )
                if await recruit.validate(
                    self.world, self.level,
                ):
                    events = await recruit.execute(
                        self.world, self.level,
                    )
                    for ev in events:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                    break  # Exit menu after hiring
