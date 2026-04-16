"""Henchman recruitment, dismissal, and item-giving actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import _count_slots_used, _entity_name, _item_slot_cost
from nhc.core.events import Event, HenchmanMenuEvent, MessageEvent
from nhc.entities.components import BlocksMovement
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

HIRE_COST_PER_LEVEL = 100
# Dungeon-mode party cap: how many henchmen can crawl a single
# dungeon with the player at once.
MAX_HENCHMEN = 2
# Overland expedition cap (hex mode): the overland roster can
# grow past the dungeon cap so the player builds a larger
# expedition. Entering a cave / ruin draws at most MAX_HENCHMEN
# of them into the crawl; settlements (towns) have no cap and
# the whole roster comes inside.
MAX_EXPEDITION = 6


def _count_hired(world: "World", player_id: int) -> int:
    """Count currently hired henchmen for a player."""
    count = 0
    for _, hench in world.query("Henchman"):
        if hench.hired and hench.owner == player_id:
            count += 1
    return count


def get_hired_henchmen(world: "World", player_id: int) -> list[int]:
    """Return entity IDs of all hired henchmen for a player."""
    result = []
    for eid, hench in world.query("Henchman"):
        if hench.hired and hench.owner == player_id:
            result.append(eid)
    return result


# ── HenchmanInteractAction ────────────────────────────────────────────

class HenchmanInteractAction(Action):
    """Open the henchman encounter menu when bumping an unhired adventurer."""

    def __init__(self, actor: int, henchman_id: int) -> None:
        super().__init__(actor)
        self.henchman_id = henchman_id

    async def validate(self, world: "World", level: "Level") -> bool:
        hench = world.get_component(self.henchman_id, "Henchman")
        if not hench or hench.hired:
            return False
        apos = world.get_component(self.actor, "Position")
        hpos = world.get_component(self.henchman_id, "Position")
        if not apos or not hpos:
            return False
        return abs(apos.x - hpos.x) <= 1 and abs(apos.y - hpos.y) <= 1

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return [HenchmanMenuEvent(henchman=self.henchman_id)]


# ── RecruitAction ──────────────────────────────────────────────────────

class RecruitAction(Action):
    """Recruit an unhired adventurer into the party.

    ``max_party`` tunes the cap the action validates against so
    the hex-mode flow can raise it to :data:`MAX_EXPEDITION` while
    the dungeon flow keeps the classic :data:`MAX_HENCHMEN`.
    """

    def __init__(
        self,
        actor: int,
        target: int,
        max_party: int = MAX_HENCHMEN,
    ) -> None:
        super().__init__(actor)
        self.target = target
        self.max_party = max_party

    async def validate(self, world: "World", level: "Level") -> bool:
        hench = world.get_component(self.target, "Henchman")
        if not hench or hench.hired:
            return False
        player = world.get_component(self.actor, "Player")
        if not player:
            return False
        # Check adjacency
        apos = world.get_component(self.actor, "Position")
        tpos = world.get_component(self.target, "Position")
        if not apos or not tpos:
            return False
        if abs(apos.x - tpos.x) > 1 or abs(apos.y - tpos.y) > 1:
            return False
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        hench = world.get_component(self.target, "Henchman")
        player = world.get_component(self.actor, "Player")
        target_name = _entity_name(world, self.target)
        cost = HIRE_COST_PER_LEVEL * hench.level

        # Show the offer
        events.append(MessageEvent(
            text=t("henchman.recruit_offer",
                    name=target_name, cost=cost),
        ))

        # Check party size against the mode-appropriate cap.
        if _count_hired(world, self.actor) >= self.max_party:
            events.append(MessageEvent(
                text=t("henchman.party_full"),
            ))
            return events

        # Check gold
        if player.gold < cost:
            events.append(MessageEvent(
                text=t("henchman.no_gold",
                        name=target_name, cost=cost),
            ))
            return events

        # Hire the adventurer
        player.gold -= cost
        hench.hired = True
        hench.owner = self.actor

        # Remove BlocksMovement so player can walk through
        world.remove_component(self.target, "BlocksMovement")

        events.append(MessageEvent(
            text=t("henchman.recruited", name=target_name),
        ))
        logger.info(
            "Recruited %s (eid=%d) at level %d for %d gold",
            target_name, self.target, hench.level, cost,
        )
        return events


# ── DismissAction ──────────────────────────────────────────────────────

class DismissAction(Action):
    """Dismiss a hired henchman from the party."""

    def __init__(self, actor: int, henchman_id: int) -> None:
        super().__init__(actor)
        self.henchman_id = henchman_id

    async def validate(self, world: "World", level: "Level") -> bool:
        hench = world.get_component(self.henchman_id, "Henchman")
        if not hench or not hench.hired:
            return False
        if hench.owner != self.actor:
            return False
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        hench = world.get_component(self.henchman_id, "Henchman")
        name = _entity_name(world, self.henchman_id)

        hench.hired = False
        hench.owner = None

        # Re-add BlocksMovement so it blocks like other NPCs
        if not world.has_component(self.henchman_id, "BlocksMovement"):
            world.add_component(
                self.henchman_id, "BlocksMovement", BlocksMovement(),
            )

        logger.info("Dismissed henchman %s (eid=%d)", name, self.henchman_id)
        return [MessageEvent(
            text=t("henchman.dismissed", name=name),
        )]


# ── GiveItemAction ─────────────────────────────────────────────────────

class GiveItemAction(Action):
    """Give an item from the player's inventory to a henchman."""

    def __init__(
        self, actor: int, henchman_id: int, item_id: int,
    ) -> None:
        super().__init__(actor)
        self.henchman_id = henchman_id
        self.item_id = item_id

    async def validate(self, world: "World", level: "Level") -> bool:
        # Actor must be the player
        if not world.has_component(self.actor, "Player"):
            return False
        # Target must be a hired henchman
        hench = world.get_component(self.henchman_id, "Henchman")
        if not hench or not hench.hired or hench.owner != self.actor:
            return False
        # Item must be in player's inventory
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item_id not in inv.slots:
            return False
        # Henchman must have inventory
        h_inv = world.get_component(self.henchman_id, "Inventory")
        if not h_inv:
            return False
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        inv = world.get_component(self.actor, "Inventory")
        h_inv = world.get_component(self.henchman_id, "Inventory")
        hench_name = _entity_name(world, self.henchman_id)
        item_name = _entity_name(world, self.item_id)

        # Check henchman has room
        used = _count_slots_used(world, h_inv)
        cost = _item_slot_cost(world, self.item_id)
        if used + cost > h_inv.max_slots:
            return [MessageEvent(
                text=t("henchman.give_full", name=hench_name),
            )]

        # Transfer
        inv.slots.remove(self.item_id)
        h_inv.slots.append(self.item_id)

        # Unequip from player if it was equipped
        equip = world.get_component(self.actor, "Equipment")
        if equip:
            for slot in ("weapon", "armor", "shield",
                         "helmet", "ring_left", "ring_right"):
                if getattr(equip, slot) == self.item_id:
                    setattr(equip, slot, None)

        # Henchman auto-equips the best available gear
        from nhc.ai.henchman_ai import auto_equip_best
        auto_equip_best(world, self.henchman_id)

        logger.info(
            "Gave %s to henchman %s", item_name, hench_name,
        )
        return [MessageEvent(
            text=t("henchman.give_item",
                    item=item_name, name=hench_name),
        )]
