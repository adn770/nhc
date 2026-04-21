"""Pickpocket action — NPC thief attempts to lift gold or an item.

The thief rolls a theft check (Knave: d20 + DEX vs 10 + target DEX)
and the target rolls an independent perception check
(d20 + WIS vs 10 + thief DEX). The two rolls are independent, so
a silent success and a caught fumble are both possible outcomes.

Only one of the four outcomes is silent: theft-fail + miss-notice
produces no message at all. Successful theft removes gold (preferred)
or a random non-equipped inventory item (equipment is safe —
equipped gear is harder to lift than loose gear in a belt pouch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import _msg
from nhc.core.events import Event, MessageEvent
from nhc.utils.rng import d20, get_rng
from nhc.utils.spatial import adjacent

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


def _equipped_item_ids(world: "World", target: int) -> set[int]:
    """Collect every equipped item entity ID on ``target``."""
    equip = world.get_component(target, "Equipment")
    if not equip:
        return set()
    ids: set[int] = set()
    for slot in (
        "weapon", "armor", "shield", "helmet",
        "ring_left", "ring_right",
    ):
        val = getattr(equip, slot, None)
        if val is not None:
            ids.add(val)
    return ids


def _non_equipped_inventory(world: "World", target: int) -> list[int]:
    """List of inventory item entity IDs that aren't equipped."""
    inv = world.get_component(target, "Inventory")
    if not inv or not inv.slots:
        return []
    equipped = _equipped_item_ids(world, target)
    return [iid for iid in inv.slots if iid not in equipped]


def player_has_stealable(world: "World", target: int) -> bool:
    """True when the player carries something a pickpocket can take."""
    player = world.get_component(target, "Player")
    if player and player.gold > 0:
        return True
    return bool(_non_equipped_inventory(world, target))


class PickpocketAction(Action):
    """Thief attempts to steal gold or an item from an adjacent target.

    Rolls are independent: theft resolves first, perception second,
    and message emission is gated on the perception result alone.
    """

    def __init__(self, actor: int, target: int) -> None:
        super().__init__(actor)
        self.target = target

    async def validate(
        self, world: "World", level: "Level",
    ) -> bool:
        apos = world.get_component(self.actor, "Position")
        tpos = world.get_component(self.target, "Position")
        if not apos or not tpos:
            return False
        if not adjacent(apos.x, apos.y, tpos.x, tpos.y):
            return False
        a_stats = world.get_component(self.actor, "Stats")
        t_stats = world.get_component(self.target, "Stats")
        if not a_stats or not t_stats:
            return False
        return True

    async def execute(
        self, world: "World", level: "Level",
    ) -> list[Event]:
        events: list[Event] = []
        a_stats = world.get_component(self.actor, "Stats")
        t_stats = world.get_component(self.target, "Stats")
        player = world.get_component(self.target, "Player")

        theft_roll = d20()
        theft_success = (
            theft_roll + a_stats.dexterity
            >= 10 + t_stats.dexterity
        )
        notice_roll = d20()
        noticed = (
            notice_roll + t_stats.wisdom
            >= 10 + a_stats.dexterity
        )

        stole_what: str | None = None
        if theft_success:
            stole_what = self._take_loot(world, player)

        if stole_what == "gold" and noticed:
            events.append(MessageEvent(
                text=_msg(
                    "pickpocket.steals_gold", world,
                    actor=self.actor,
                    amount=self._last_amount,
                ),
                actor=self.actor,
            ))
        elif stole_what == "item" and noticed:
            events.append(MessageEvent(
                text=_msg(
                    "pickpocket.steals_item", world,
                    actor=self.actor,
                    item=self._last_item_name,
                ),
                actor=self.actor,
            ))
        elif not theft_success and noticed:
            events.append(MessageEvent(
                text=_msg(
                    "pickpocket.caught_fumble", world,
                    actor=self.actor,
                ),
                actor=self.actor,
            ))
        # theft_success but stole_what is None: target carried
        # nothing to take — silent pass. theft_fail + unseen: silent.

        return events

    def _take_loot(
        self, world: "World", player,
    ) -> str | None:
        """Lift gold (preferred) or a random non-equipped item.

        Populates ``_last_amount`` / ``_last_item_name`` for the
        message builder. Returns ``"gold"``, ``"item"``, or
        ``None`` when the target is empty.
        """
        rng = get_rng()
        self._last_amount = 0
        self._last_item_name = ""

        if player is not None and player.gold > 0:
            amount = min(player.gold, rng.randint(1, 20))
            player.gold -= amount
            self._last_amount = amount
            return "gold"

        stealable = _non_equipped_inventory(world, self.target)
        if not stealable:
            return None
        target_iid = rng.choice(stealable)
        inv = world.get_component(self.target, "Inventory")
        desc = world.get_component(target_iid, "Description")
        self._last_item_name = desc.name if desc else "item"
        if inv and target_iid in inv.slots:
            inv.slots.remove(target_iid)
        if target_iid in world._entities:
            world.destroy_entity(target_iid)
        return "item"
