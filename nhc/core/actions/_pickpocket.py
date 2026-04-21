"""Pickpocket action — NPC thief attempts to lift gold or an item.

The thief rolls a theft check (Knave: d20 + DEX vs 10 + target DEX)
and the target rolls an independent perception check
(d20 + WIS vs 10 + thief DEX). The two rolls are independent, so
a silent success and a caught fumble are both possible outcomes.

Only one of the four outcomes is silent: theft-fail + miss-notice
produces no message at all. Successful theft removes gold (preferred)
or a random non-equipped inventory item (equipment is safe —
equipped gear is harder to lift than loose gear in a belt pouch).

On any noticed outcome (success *or* fail) the thief reacts: blend
back into the crowd when enough humanoid neighbours are nearby,
otherwise flee to the town edge and despawn on arrival.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import _msg
from nhc.core.events import Event, MessageEvent
from nhc.utils.rng import d20, get_rng
from nhc.utils.spatial import adjacent, chebyshev

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


# Radius (chebyshev) within which other humanoid NPCs count as
# "crowd cover" that lets a caught pickpocket blend back into the
# errand flow instead of fleeing.
_BLEND_RADIUS = 5
# Minimum neighbouring humanoids required to blend. Two bystanders
# give the thief a plausible crowd to disappear into; with fewer,
# the player would trivially spot which tile the message pointed at.
_BLEND_THRESHOLD = 2


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

        if noticed:
            react_to_notice(world, level, self.actor)

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


def _count_crowd_cover(
    world: "World", thief_id: int, tx: int, ty: int,
) -> int:
    """Count humanoid NPCs (excluding the thief) within the blend
    radius. Player and hired henchmen do not count — only other
    villagers, pickpockets, and service NPCs can provide cover."""
    from nhc.ai.behavior import HUMANOID_FACTIONS

    count = 0
    for eid, ai, pos in world.query("AI", "Position"):
        if eid == thief_id:
            continue
        if world.has_component(eid, "Player"):
            continue
        hench = world.get_component(eid, "Henchman")
        if hench and hench.hired:
            continue
        if ai.faction not in HUMANOID_FACTIONS:
            continue
        if chebyshev(tx, ty, pos.x, pos.y) <= _BLEND_RADIUS:
            count += 1
    return count


def _nearest_edge_tile(
    world: "World", level: "Level", thief_id: int, tx: int, ty: int,
) -> tuple[int, int] | None:
    """Nearest walkable level-perimeter tile by chebyshev distance.

    Skips tiles with a feature (door/stairs) so the fleeing thief
    does not stumble into a building interior, and tiles occupied
    by other blockers so the despawn spot is actually reachable.
    """
    from nhc.ai.behavior import _ERRAND_BLOCKING_FEATURES

    w, h = level.width, level.height
    best: tuple[int, int] | None = None
    best_d = 10 ** 9
    for y in range(h):
        for x in range(w):
            on_edge = x == 0 or y == 0 or x == w - 1 or y == h - 1
            if not on_edge:
                continue
            tile = level.tile_at(x, y)
            if not tile or not tile.walkable:
                continue
            if tile.feature in _ERRAND_BLOCKING_FEATURES:
                continue
            occupied = False
            for eid, _, bpos in world.query(
                "BlocksMovement", "Position",
            ):
                if eid == thief_id:
                    continue
                if bpos.x == x and bpos.y == y:
                    occupied = True
                    break
            if occupied:
                continue
            d = chebyshev(tx, ty, x, y)
            if d < best_d:
                best_d = d
                best = (x, y)
    return best


def react_to_notice(
    world: "World", level: "Level", thief_id: int,
) -> None:
    """Resolve a caught pickpocket: blend back in or flee to an edge.

    Blend path: at least ``_BLEND_THRESHOLD`` other humanoid NPCs
    sit within ``_BLEND_RADIUS`` chebyshev tiles. The thief becomes
    visually and mechanically indistinguishable from a villager —
    AI.behavior flips to ``"errand"`` and the Thief component is
    removed so it never rearms for another lift.

    Flee path: the thief sets a flee target on the nearest walkable
    perimeter tile of the level and flips its ``fleeing`` flag.
    ``_decide_thief_action`` takes it from there (path + despawn on
    arrival). If no edge is reachable the thief also blends as a
    graceful fallback.
    """
    pos = world.get_component(thief_id, "Position")
    ai = world.get_component(thief_id, "AI")
    thief = world.get_component(thief_id, "Thief")
    if not pos or not ai or not thief:
        return

    crowd = _count_crowd_cover(world, thief_id, pos.x, pos.y)
    if crowd >= _BLEND_THRESHOLD:
        _blend_into_crowd(world, thief_id, ai)
        return

    edge = _nearest_edge_tile(world, level, thief_id, pos.x, pos.y)
    if edge is None:
        _blend_into_crowd(world, thief_id, ai)
        return
    thief.fleeing = True
    thief.flee_target_x, thief.flee_target_y = edge


def _blend_into_crowd(
    world: "World", thief_id: int, ai,
) -> None:
    ai.behavior = "errand"
    if world.has_component(thief_id, "Thief"):
        world.remove_component(thief_id, "Thief")
