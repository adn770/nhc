"""Creature AI behavior: decide what action to take each turn."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.ai.pathfinding import astar
from nhc.entities.components import AI, Position
from nhc.utils.spatial import adjacent, chebyshev

if TYPE_CHECKING:
    from nhc.core.actions import Action
    from nhc.core.ecs import EntityId, World
    from nhc.dungeon.model import Level


# Maximum chase distance per behavior type
CHASE_RADIUS: dict[str, int] = {
    "aggressive_melee": 8,
    "guard": 5,
    "idle": 0,
}


def decide_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Determine what action a creature should take this turn."""
    from nhc.core.actions import MeleeAttackAction, MoveAction

    ai = world.get_component(entity_id, "AI")
    pos = world.get_component(entity_id, "Position")
    player_pos = world.get_component(player_id, "Position")

    if not ai or not pos or not player_pos:
        return None

    dist = chebyshev(pos.x, pos.y, player_pos.x, player_pos.y)
    chase_radius = CHASE_RADIUS.get(ai.behavior, 0)

    if chase_radius == 0:
        return None

    # Adjacent: attack
    if adjacent(pos.x, pos.y, player_pos.x, player_pos.y):
        return MeleeAttackAction(actor=entity_id, target=player_id)

    # Within chase range: pathfind toward player
    if dist <= chase_radius:
        def is_walkable(x: int, y: int) -> bool:
            tile = level.tile_at(x, y)
            if not tile or not tile.walkable:
                return False
            # Don't walk through other creatures (except target)
            if (x, y) == (player_pos.x, player_pos.y):
                return True
            for eid, _, bpos in world.query("BlocksMovement", "Position"):
                if bpos.x == x and bpos.y == y and eid != entity_id:
                    return False
            return True

        path = astar((pos.x, pos.y), (player_pos.x, player_pos.y), is_walkable)
        if path:
            nx, ny = path[0]
            dx = nx - pos.x
            dy = ny - pos.y
            return MoveAction(actor=entity_id, dx=dx, dy=dy)

    return None
