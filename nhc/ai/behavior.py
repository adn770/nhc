"""Creature AI behavior: decide what action to take each turn."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from nhc.ai.pathfinding import astar
from nhc.entities.components import (
    AI,
    CharmSong,
    DeathWail,
    FearAura,
    Position,
    StatusEffect,
)
from nhc.core.actions._helpers import has_ring_effect
from nhc.utils.rng import d20
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
    "shrieker": 5,  # detection range; shrieker never moves
}


def decide_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Determine what action a creature should take this turn."""
    from nhc.core.actions import (
        BansheeWailAction,
        MeleeAttackAction,
        MoveAction,
        ShriekAction,
    )

    ai = world.get_component(entity_id, "AI")
    pos = world.get_component(entity_id, "Position")
    player_pos = world.get_component(player_id, "Position")

    if not ai or not pos or not player_pos:
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

    dist = chebyshev(pos.x, pos.y, player_pos.x, player_pos.y)
    chase_radius = CHASE_RADIUS.get(ai.behavior, 0)

    # Ring of shadows: halve all detection ranges
    if has_ring_effect(world, player_id, "shadows"):
        chase_radius = chase_radius // 2

    # Shrieker: stationary; screams when player enters detection range
    if ai.behavior == "shrieker":
        if dist <= chase_radius:
            return ShriekAction(actor=entity_id)
        return None

    # Banshee: wail when player is in range, then also attack if adjacent
    shadows = has_ring_effect(world, player_id, "shadows")
    death_wail = world.get_component(entity_id, "DeathWail")
    if death_wail:
        wail_range = death_wail.radius // 2 if shadows else death_wail.radius
        if dist <= wail_range:
            return BansheeWailAction(actor=entity_id, player_id=player_id)

    # FearAura: player must save STR or be webbed (paralyzed with fear)
    fear_aura = world.get_component(entity_id, "FearAura")
    fear_range = fear_aura.radius // 2 if fear_aura and shadows else (fear_aura.radius if fear_aura else 0)
    if fear_aura and dist <= fear_range:
        p_stats = world.get_component(player_id, "Stats")
        if p_stats:
            player_status = world.get_component(player_id, "StatusEffect")
            # Only apply fear if not already paralyzed/feared
            if (player_status is None or player_status.webbed == 0) and \
               d20() + p_stats.strength < fear_aura.save_dc:
                if player_status is None:
                    world.add_component(player_id, "StatusEffect",
                                        StatusEffect(webbed=1))
                else:
                    player_status.webbed = 1

    # CharmSong: force player toward creature each turn (skip player turn)
    charm_song = world.get_component(entity_id, "CharmSong")
    charm_range = charm_song.radius // 2 if charm_song and shadows else (charm_song.radius if charm_song else 0)
    if charm_song and dist <= charm_range:
        p_stats = world.get_component(player_id, "Stats")
        if p_stats:
            player_status = world.get_component(player_id, "StatusEffect")
            if (player_status is None or player_status.charmed == 0) and \
               d20() + p_stats.wisdom < charm_song.save_dc:
                if player_status is None:
                    world.add_component(player_id, "StatusEffect",
                                        StatusEffect(charmed=2))
                else:
                    player_status.charmed = 2

    if chase_radius == 0:
        return None

    # Adjacent: attack
    if adjacent(pos.x, pos.y, player_pos.x, player_pos.y):
        logger.debug("AI entity=%d attacks player (adjacent)", entity_id)
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
