"""Henchman AI: follow the player, fight, heal, search, pick up items.

Unhired adventurers share this module but route to a separate wander
behaviour — they roam the current level, flee from monsters, and only
fight when cornered.  Recruiting them flips them into the full hired
behaviour below.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.ai.pathfinding import astar
from nhc.utils.rng import get_rng
from nhc.utils.spatial import adjacent, chebyshev

if TYPE_CHECKING:
    from nhc.core.actions import Action
    from nhc.core.ecs import EntityId, World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)

# Henchman will follow when player is farther than this
FOLLOW_DISTANCE = 6

# Tile features an unhired wanderer will not willingly step onto.
# Descending stairs is how the player transitions levels, and the
# whole point of "unhired" is that they stay on this floor.
_FORBIDDEN_WANDER_FEATURES = frozenset({"stairs_down", "stairs_up"})


def _find_room(level: "Level", x: int, y: int) -> object | None:
    """Return the room containing (x, y), or None."""
    for room in level.rooms:
        if (x, y) in room.floor_tiles():
            return room
    return None


def _find_hostile_adjacent(
    entity_id: int,
    world: "World",
    pos: object,
) -> int | None:
    """Return entity ID of an adjacent hostile creature, or None."""
    for eid, ai, epos in world.query("AI", "Position"):
        if eid == entity_id:
            continue
        # Skip other henchmen
        hench = world.get_component(eid, "Henchman")
        if hench and hench.hired:
            continue
        # Skip non-aggressive creatures
        if ai.behavior == "idle":
            continue
        if adjacent(pos.x, pos.y, epos.x, epos.y):
            return eid
    return None


def _find_potion_healing(world: "World", entity_id: int) -> int | None:
    """Return entity ID of a healing potion in inventory, or None."""
    inv = world.get_component(entity_id, "Inventory")
    if not inv:
        return None
    for item_id in inv.slots:
        consumable = world.get_component(item_id, "Consumable")
        if consumable and consumable.effect == "heal":
            return item_id
    return None


def _find_items_at(
    world: "World",
    x: int, y: int,
    entity_id: int,
) -> list[int]:
    """Return item entity IDs on the floor at (x, y), excluding gold."""
    items = []
    for eid, epos in world.query("Position"):
        if epos.x != x or epos.y != y:
            continue
        if eid == entity_id:
            continue
        # Must be an item (has Description, no AI, no BlocksMovement)
        if world.has_component(eid, "AI"):
            continue
        if world.has_component(eid, "BlocksMovement"):
            continue
        if world.has_component(eid, "Gold"):
            continue
        if not world.get_component(eid, "Description"):
            continue
        # Must be a carriable item (weapon, armor, consumable, etc.)
        is_item = (
            world.has_component(eid, "Weapon")
            or world.has_component(eid, "Armor")
            or world.has_component(eid, "Consumable")
            or world.has_component(eid, "Ring")
            or world.has_component(eid, "Wand")
            or world.has_component(eid, "DiggingTool")
        )
        if is_item:
            items.append(eid)
    return items


def decide_henchman_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Determine what action a hired henchman should take."""
    from nhc.core.actions import (
        MeleeAttackAction,
        MoveAction,
        PickupItemAction,
        SearchAction,
        UseItemAction,
    )

    # Unhired adventurers use the lightweight wander behaviour —
    # they live in the dungeon on their own until recruited.
    hench = world.get_component(entity_id, "Henchman")
    if not hench or not hench.hired:
        return decide_unhired_wander_action(entity_id, world, level)

    pos = world.get_component(entity_id, "Position")
    player_pos = world.get_component(player_id, "Position")
    if not pos or not player_pos:
        return None

    # Status effects: skip turn when immobilised
    status = world.get_component(entity_id, "StatusEffect")
    if status:
        if status.paralyzed > 0:
            status.paralyzed -= 1
            return None
        if status.sleeping > 0:
            status.sleeping -= 1
            return None
        if status.webbed > 0:
            status.webbed -= 1
            return None
        if status.charmed > 0:
            status.charmed -= 1
            return None

    # 1. Heal self if HP < 50%
    health = world.get_component(entity_id, "Health")
    if health and health.current < health.maximum // 2:
        potion = _find_potion_healing(world, entity_id)
        if potion:
            logger.debug("Henchman %d uses healing potion", entity_id)
            return UseItemAction(actor=entity_id, item=potion)

    # 2. Fight adjacent hostile creature
    hostile = _find_hostile_adjacent(entity_id, world, pos)
    if hostile:
        logger.debug("Henchman %d attacks hostile %d", entity_id, hostile)
        return MeleeAttackAction(actor=entity_id, target=hostile)

    dist = chebyshev(pos.x, pos.y, player_pos.x, player_pos.y)

    # 3. Follow player if too far away
    if dist > FOLLOW_DISTANCE:
        path = _pathfind_toward(
            entity_id, pos, player_pos, world, level, player_id,
        )
        if path:
            nx, ny = path[0]
            return MoveAction(
                actor=entity_id,
                dx=nx - pos.x,
                dy=ny - pos.y,
            )

    # 4. Check if in the same room as the player
    player_room = _find_room(level, player_pos.x, player_pos.y)
    hench_room = _find_room(level, pos.x, pos.y)

    # Follow if in different rooms, or if either is in a corridor
    # and they're more than 1 tile apart
    should_follow = False
    if player_room and hench_room and player_room != hench_room:
        should_follow = True
    elif (player_room is None or hench_room is None) and dist > 1:
        should_follow = True

    if should_follow:
        path = _pathfind_toward(
            entity_id, pos, player_pos, world, level, player_id,
        )
        if path:
            nx, ny = path[0]
            return MoveAction(
                actor=entity_id,
                dx=nx - pos.x,
                dy=ny - pos.y,
            )

    # 5. In-room behaviors (same room as player or corridors)

    # Pick up items on current tile
    items = _find_items_at(world, pos.x, pos.y, entity_id)
    if items:
        inv = world.get_component(entity_id, "Inventory")
        if inv and len(inv.slots) < inv.max_slots:
            return PickupItemAction(
                actor=entity_id, item=items[0],
            )

    rng = get_rng()

    # Search for secrets (20% chance per turn)
    if rng.random() < 0.2:
        return SearchAction(actor=entity_id)

    # Wander within room
    if hench_room:
        floor = list(hench_room.floor_tiles())
        rng.shuffle(floor)
        for fx, fy in floor:
            if adjacent(pos.x, pos.y, fx, fy):
                # Don't walk onto blockers or allies
                blocked = False
                for _, _, bpos in world.query(
                    "BlocksMovement", "Position",
                ):
                    if bpos.x == fx and bpos.y == fy:
                        blocked = True
                        break
                if not blocked and _is_occupied_by_ally(
                    world, fx, fy, entity_id, player_id,
                ):
                    blocked = True
                if not blocked:
                    return MoveAction(
                        actor=entity_id,
                        dx=fx - pos.x,
                        dy=fy - pos.y,
                    )

    return None


def _is_occupied_by_ally(
    world: "World",
    x: int, y: int,
    entity_id: int,
    player_id: int,
) -> bool:
    """True if (x, y) is occupied by the player or another henchman."""
    player_pos = world.get_component(player_id, "Position")
    if player_pos and player_pos.x == x and player_pos.y == y:
        return True
    for eid, hench in world.query("Henchman"):
        if eid == entity_id or not hench.hired:
            continue
        hpos = world.get_component(eid, "Position")
        if hpos and hpos.x == x and hpos.y == y:
            return True
    return False


def _pathfind_toward(
    entity_id: int,
    pos: object,
    target_pos: object,
    world: "World",
    level: "Level",
    player_id: int | None = None,
) -> list[tuple[int, int]] | None:
    """A* pathfind toward target, returning the path."""
    def is_walkable(x: int, y: int) -> bool:
        tile = level.tile_at(x, y)
        if not tile or not tile.walkable:
            return False
        if (x, y) == (target_pos.x, target_pos.y):
            return True
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == x and bpos.y == y and eid != entity_id:
                return False
        return True

    path = astar(
        (pos.x, pos.y), (target_pos.x, target_pos.y), is_walkable,
    )
    if not path:
        return None

    # Don't step onto allies (player or other henchmen)
    if player_id is not None and path:
        nx, ny = path[0]
        if _is_occupied_by_ally(world, nx, ny, entity_id, player_id):
            # Stop one tile away — don't walk onto ally
            return None

    return path


# ── Unhired wander behaviour ──────────────────────────────────────────


def _find_threat_adjacent(
    entity_id: int,
    world: "World",
    pos: object,
) -> int | None:
    """Find an adjacent aggressive creature (not a fellow henchman)."""
    for eid, ai, epos in world.query("AI", "Position"):
        if eid == entity_id:
            continue
        # Ignore peers and passive creatures
        if ai.behavior in ("henchman", "idle", "shrieker"):
            continue
        if adjacent(pos.x, pos.y, epos.x, epos.y):
            return eid
    return None


def _wander_walkable(
    world: "World",
    level: "Level",
    x: int, y: int,
    entity_id: int,
) -> bool:
    """Whether an unhired adventurer may step into (x, y)."""
    tile = level.tile_at(x, y)
    if not tile or not tile.walkable:
        return False
    if tile.feature in _FORBIDDEN_WANDER_FEATURES:
        return False
    for eid, _, bpos in world.query("BlocksMovement", "Position"):
        if bpos.x == x and bpos.y == y and eid != entity_id:
            return False
    return True


def decide_unhired_wander_action(
    entity_id: int,
    world: "World",
    level: "Level",
) -> "Action | None":
    """Drift around the level; flee from threats or fight if cornered.

    Unhired adventurers are independent NPCs — they explore the
    current floor, retreat from monsters, and defend themselves when
    they cannot run.  They never pathfind toward the player and
    never willingly step onto stairs, so they remain on the level
    where they were generated until the player recruits them.
    """
    from nhc.core.actions import MeleeAttackAction, MoveAction

    pos = world.get_component(entity_id, "Position")
    if not pos:
        return None

    # Respect incapacitating status effects.
    status = world.get_component(entity_id, "StatusEffect")
    if status:
        if status.paralyzed > 0:
            status.paralyzed -= 1
            return None
        if status.sleeping > 0:
            status.sleeping -= 1
            return None
        if status.webbed > 0:
            status.webbed -= 1
            return None
        if status.charmed > 0:
            status.charmed -= 1
            return None

    threat = _find_threat_adjacent(entity_id, world, pos)
    if threat is not None:
        tpos = world.get_component(threat, "Position")
        # Pick the adjacent step that maximises distance from the
        # threat — chebyshev so diagonals count as one tile.
        best: tuple[int, int] | None = None
        best_dist = chebyshev(pos.x, pos.y, tpos.x, tpos.y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = pos.x + dx, pos.y + dy
                if not _wander_walkable(
                    world, level, nx, ny, entity_id,
                ):
                    continue
                d = chebyshev(nx, ny, tpos.x, tpos.y)
                if d > best_dist:
                    best_dist = d
                    best = (dx, dy)
        if best is not None:
            return MoveAction(
                actor=entity_id, dx=best[0], dy=best[1],
            )
        # No retreat available — fight for survival.
        return MeleeAttackAction(actor=entity_id, target=threat)

    # No visible threat — drift into a random adjacent walkable tile.
    rng = get_rng()
    steps = [
        (dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
        if (dx, dy) != (0, 0)
    ]
    rng.shuffle(steps)
    for dx, dy in steps:
        nx, ny = pos.x + dx, pos.y + dy
        if _wander_walkable(world, level, nx, ny, entity_id):
            return MoveAction(actor=entity_id, dx=dx, dy=dy)

    return None
