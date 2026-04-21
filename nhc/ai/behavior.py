"""Creature AI behavior: decide what action to take each turn."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from nhc.ai.pathfinding import astar
from nhc.ai.retreat import best_retreat_step
from nhc.ai.tactics import morale_check
from nhc.entities.components import (
    AI,
    CharmSong,
    DeathWail,
    FearAura,
    Position,
    StatusEffect,
)
from nhc.core.actions._helpers import _msg, has_ring_effect
from nhc.utils.rng import d20, get_rng
from nhc.utils.spatial import adjacent, chebyshev

if TYPE_CHECKING:
    from nhc.core.actions import Action
    from nhc.core.ecs import EntityId, World
    from nhc.dungeon.model import Level


# Factions whose creatures can open closed doors
HUMANOID_FACTIONS: frozenset[str] = frozenset({
    "goblinoid", "human", "humanoid", "giant", "gnoll", "undead",
})

# Maximum chase distance per behavior type
CHASE_RADIUS: dict[str, int] = {
    "aggressive_melee": 8,
    "guard": 5,
    "idle": 0,
    "shrieker": 5,  # detection range; shrieker never moves
    "errand": 0,    # town villagers never chase
    "thief": 0,     # pickpockets wander + lift; never combat
}

# Tile features an errand NPC will not step onto. Door tiles
# trigger interior teleport on entry, which would whisk a villager
# into a building off-screen; keeping them on the surface means the
# player reliably sees the crowd.
_ERRAND_BLOCKING_FEATURES: frozenset[str] = frozenset({
    "door_closed", "door_open", "door_locked", "door_secret",
    "stairs_up", "stairs_down",
})

# How long an errand NPC lingers at its destination before picking
# the next one. Roughly "visiting a shop / chatting at a stall".
_ERRAND_IDLE_TURNS_RANGE = (3, 8)


def _find_attack_targets(
    entity_id: int,
    world: "World",
    pos: "Position",
    player_id: int,
) -> list[int]:
    """Find adjacent entities this creature can attack.

    Returns player and/or hired henchmen that are adjacent,
    sorted by distance (nearest first, random on tie).
    """
    from nhc.utils.rng import get_rng

    targets: list[int] = []

    # Check player
    player_pos = world.get_component(player_id, "Position")
    if player_pos and adjacent(pos.x, pos.y, player_pos.x, player_pos.y):
        targets.append(player_id)

    # Check henchmen
    for eid, hench in world.query("Henchman"):
        if not hench.hired:
            continue
        hpos = world.get_component(eid, "Position")
        if hpos and adjacent(pos.x, pos.y, hpos.x, hpos.y):
            targets.append(eid)

    # Shuffle so ties are random
    if len(targets) > 1:
        get_rng().shuffle(targets)

    return targets


def _aggressive_behavior(behavior: str) -> bool:
    """Behaviors whose creatures roll morale at all.

    Idle / shrieker / henchman creatures have their own decision
    pipelines and never enter the morale state machine.
    """
    return behavior in ("aggressive_melee", "guard")


def _decide_flee_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Move one tile strictly away from the player.

    Used by morale-broken creatures in the ``fleeing`` state.
    Falls back to the cornered melee swing when no retreat tile
    is available — this matches the unhired-adventurer logic
    and prevents fleeing creatures from getting stuck in place.
    """
    from nhc.core.actions import HoldAction, MeleeAttackAction, MoveAction

    pos = world.get_component(entity_id, "Position")
    player_pos = world.get_component(player_id, "Position")
    if not pos or not player_pos:
        return None

    def is_walkable(x: int, y: int) -> bool:
        tile = level.tile_at(x, y)
        if not tile or not tile.walkable:
            return False
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == x and bpos.y == y and eid != entity_id:
                return False
        return True

    step = best_retreat_step(
        (pos.x, pos.y),
        (player_pos.x, player_pos.y),
        is_walkable,
    )
    if step is not None:
        return MoveAction(actor=entity_id, dx=step[0], dy=step[1])

    # Cornered: swing back if adjacent, otherwise hold and snarl.
    if adjacent(pos.x, pos.y, player_pos.x, player_pos.y):
        return MeleeAttackAction(actor=entity_id, target=player_id)
    return HoldAction(
        actor=entity_id,
        message_text=_msg("morale.cornered", world, actor=entity_id),
    )


def _errand_walkable(
    world: "World",
    level: "Level",
    x: int,
    y: int,
    entity_id: int,
) -> bool:
    """Whether an errand NPC may stand on ``(x, y)``."""
    tile = level.tile_at(x, y)
    if not tile or not tile.walkable:
        return False
    if tile.feature in _ERRAND_BLOCKING_FEATURES:
        return False
    for eid, _, bpos in world.query("BlocksMovement", "Position"):
        if bpos.x == x and bpos.y == y and eid != entity_id:
            return False
    return True


def _pick_errand_destination(
    world: "World",
    level: "Level",
    pos: "Position",
    entity_id: int,
) -> tuple[int, int] | None:
    """Pick a fresh destination for an errand NPC.

    Prefers street tiles adjacent to a door feature (~40% of the
    time) so villagers visibly gather near shops and homes; falls
    back to any walkable street tile.
    """
    rng = get_rng()
    candidates: list[tuple[int, int]] = []
    door_adjacent: list[tuple[int, int]] = []
    for y in range(level.height):
        row = level.tiles[y]
        for x in range(level.width):
            if (x, y) == (pos.x, pos.y):
                continue
            if not _errand_walkable(world, level, x, y, entity_id):
                continue
            candidates.append((x, y))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < level.width
                        and 0 <= ny < level.height):
                    continue
                feat = level.tiles[ny][nx].feature
                if feat is not None and feat.startswith("door_"):
                    door_adjacent.append((x, y))
                    break
    if not candidates:
        return None
    if door_adjacent and rng.random() < 0.4:
        return rng.choice(door_adjacent)
    return rng.choice(candidates)


def _decide_errand_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Tick an errand NPC: idle → pick target → walk one step."""
    from nhc.core.actions import HoldAction, MoveAction

    errand = world.get_component(entity_id, "Errand")
    pos = world.get_component(entity_id, "Position")
    if not errand or not pos:
        return None

    if errand.idle_turns_remaining > 0:
        errand.idle_turns_remaining -= 1
        return HoldAction(actor=entity_id)

    if errand.target_x is None or errand.target_y is None:
        target = _pick_errand_destination(
            world, level, pos, entity_id,
        )
        if target is None:
            return HoldAction(actor=entity_id)
        errand.target_x, errand.target_y = target

    target_xy = (errand.target_x, errand.target_y)
    if (pos.x, pos.y) == target_xy:
        lo, hi = _ERRAND_IDLE_TURNS_RANGE
        errand.idle_turns_remaining = get_rng().randint(lo, hi)
        errand.target_x = None
        errand.target_y = None
        return HoldAction(actor=entity_id)

    def is_walkable(x: int, y: int) -> bool:
        if (x, y) == target_xy:
            # Always allow the goal tile itself (blocker check
            # already ran when we picked the destination).
            tile = level.tile_at(x, y)
            if not tile or not tile.walkable:
                return False
            return tile.feature not in _ERRAND_BLOCKING_FEATURES
        return _errand_walkable(world, level, x, y, entity_id)

    edge_blocks = None
    if level.interior_edges:
        from nhc.dungeon.edges import edge_blocks_movement

        def edge_blocks(a, b):
            return edge_blocks_movement(level, a, b)

    path = astar(
        (pos.x, pos.y), target_xy, is_walkable,
        edge_blocks=edge_blocks,
    )
    if not path:
        # Unreachable — drop the target and idle a beat so the
        # next tick rolls a fresh one.
        errand.target_x = None
        errand.target_y = None
        return HoldAction(actor=entity_id)

    nx, ny = path[0]
    return MoveAction(actor=entity_id, dx=nx - pos.x, dy=ny - pos.y)


def _decide_thief_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Thief tick: wander like a villager until adjacent to the
    player, then attempt one theft per adjacency streak.

    Cooldown lives on the ``Thief`` component: ``attempted_in_streak``
    flips True after a theft roll fires and only resets when the
    thief breaks adjacency again. Without the cooldown, a thief could
    pick the player clean in a single stand-still encounter.
    """
    from nhc.core.actions import PickpocketAction, player_has_stealable

    thief = world.get_component(entity_id, "Thief")
    pos = world.get_component(entity_id, "Position")
    player_pos = world.get_component(player_id, "Position")
    if not thief or not pos or not player_pos:
        return None

    is_adj = adjacent(pos.x, pos.y, player_pos.x, player_pos.y)

    if not is_adj:
        thief.attempted_in_streak = False
        return _decide_errand_action(
            entity_id, world, level, player_id,
        )

    if thief.attempted_in_streak:
        return _decide_errand_action(
            entity_id, world, level, player_id,
        )

    if not player_has_stealable(world, player_id):
        return _decide_errand_action(
            entity_id, world, level, player_id,
        )

    thief.attempted_in_streak = True
    return PickpocketAction(actor=entity_id, target=player_id)


def decide_action(
    entity_id: int,
    world: "World",
    level: "Level",
    player_id: int,
) -> "Action | None":
    """Determine what action a creature should take this turn."""
    from nhc.core.actions import (
        BansheeWailAction,
        HoldAction,
        MeleeAttackAction,
        MoveAction,
        ShriekAction,
    )

    ai = world.get_component(entity_id, "AI")
    pos = world.get_component(entity_id, "Position")
    player_pos = world.get_component(player_id, "Position")

    if not ai or not pos or not player_pos:
        return None

    # Henchman AI is handled separately
    if ai.behavior == "henchman":
        from nhc.ai.henchman_ai import decide_henchman_action
        return decide_henchman_action(
            entity_id, world, level, player_id,
        )

    # Non-combat town behavior: errand NPCs never engage the player.
    if ai.behavior == "errand":
        return _decide_errand_action(
            entity_id, world, level, player_id,
        )

    # Pickpockets wander like villagers but lift on adjacency.
    if ai.behavior == "thief":
        return _decide_thief_action(
            entity_id, world, level, player_id,
        )

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

    # ── Morale state machine (Knave / Basic D&D 2d6 ≤ morale) ──
    # Only aggressive_melee / guard creatures roll morale; others
    # have their own pipelines (shrieker, idle, special auras).
    if _aggressive_behavior(ai.behavior) and dist <= chase_radius:
        if ai.state == "fleeing":
            return _decide_flee_action(
                entity_id, world, level, player_id,
            )
        if ai.state == "unaware":
            if morale_check(ai.morale):
                ai.state = "engaged"
                # fall through to existing chase / attack logic
            else:
                ai.state = "hesitant"
                return HoldAction(
                    actor=entity_id,
                    message_text=_msg(
                        "morale.hesitate", world, actor=entity_id,
                    ),
                )
        elif ai.state == "hesitant":
            if morale_check(ai.morale):
                ai.state = "engaged"
                # Spend this turn shouting the rally; attack
                # resumes next tick. Keeps the narration cleanly
                # attached to the transition.
                return HoldAction(
                    actor=entity_id,
                    message_text=_msg(
                        "morale.rally", world, actor=entity_id,
                    ),
                )
            # Continued hesitation: stay silent so the log does
            # not spam the player every turn.
            return HoldAction(actor=entity_id)
        # ai.state == "engaged" → fall through to chase / attack

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

    # Adjacent: attack player or henchman (pick nearest/random)
    targets = _find_attack_targets(
        entity_id, world, pos, player_id,
    )
    if targets:
        target = targets[0]
        logger.debug(
            "AI entity=%d attacks target=%d (adjacent)", entity_id, target,
        )
        return MeleeAttackAction(actor=entity_id, target=target)

    # Find nearest chase target (player or hired henchman)
    chase_target_pos = player_pos
    chase_dist = dist

    for eid, hench in world.query("Henchman"):
        if not hench.hired:
            continue
        hpos = world.get_component(eid, "Position")
        if not hpos:
            continue
        h_dist = chebyshev(pos.x, pos.y, hpos.x, hpos.y)
        if h_dist < chase_dist:
            chase_dist = h_dist
            chase_target_pos = hpos

    # Within chase range: pathfind toward nearest target
    if chase_dist <= chase_radius:
        can_open_doors = ai.faction in HUMANOID_FACTIONS

        target_xy = (chase_target_pos.x, chase_target_pos.y)

        def is_walkable(x: int, y: int) -> bool:
            tile = level.tile_at(x, y)
            if not tile or not tile.walkable:
                return False
            # Non-humanoids cannot path through closed/locked doors
            if (not can_open_doors
                    and tile.feature in ("door_closed", "door_locked")):
                return False
            # Don't walk through other creatures (except target)
            if (x, y) == target_xy:
                return True
            for eid, _, bpos in world.query("BlocksMovement", "Position"):
                if bpos.x == x and bpos.y == y and eid != entity_id:
                    return False
            return True

        edge_blocks = None
        if level.interior_edges:
            from nhc.dungeon.edges import edge_blocks_movement

            def edge_blocks(a, b):
                return edge_blocks_movement(level, a, b)

        path = astar(
            (pos.x, pos.y), target_xy, is_walkable,
            edge_blocks=edge_blocks,
        )
        if path:
            nx, ny = path[0]
            dx = nx - pos.x
            dy = ny - pos.y
            return MoveAction(actor=entity_id, dx=dx, dy=dy)

    return None
