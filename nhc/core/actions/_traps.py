"""Trap detection and effect application."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.core.actions._helpers import _entity_name, _msg, has_ring_effect
from nhc.core.events import Event, MessageEvent, TrapTriggered
from nhc.entities.components import Poison, Position, StatusEffect
from nhc.rules.combat import apply_damage
from nhc.utils.rng import d20, roll_dice

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.entities.components import Trap

logger = logging.getLogger(__name__)


def _check_traps(
    world: "World", level: "Level", entity_id: int, x: int, y: int,
) -> list[Event]:
    """Check if stepping on a tile triggers a trap entity."""
    events: list[Event] = []

    for eid, trap, tpos in world.query("Trap", "Position"):
        if tpos is None or tpos.x != x or tpos.y != y:
            continue
        if trap.triggered:
            continue

        # Levitating creatures float over traps
        status = world.get_component(entity_id, "StatusEffect")
        if status and (status.levitating > 0 or status.flying > 0):
            continue

        # DEX save vs trap DC
        stats = world.get_component(entity_id, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        save_roll = d20()

        trap_desc = world.get_component(eid, "Description")
        trap_name = trap_desc.name if trap_desc else "a trap"

        if save_roll + dex_bonus >= trap.dc:
            events.append(MessageEvent(
                text=_msg("trap.avoided", world,
                          actor=entity_id, trap=trap_name),
            ))
        else:
            events += _apply_trap_effect(
                world, level, entity_id, trap, trap_name,
            )

        trap.triggered = True
        trap.hidden = False
        trap.triggered_at_turn = world.turn

    return events


def _apply_trap_effect(
    world: "World", level: "Level", entity_id: int,
    trap: "Trap", trap_name: str,
) -> list[Event]:
    """Apply the specific effect of a triggered trap."""
    events: list[Event] = []
    health = world.get_component(entity_id, "Health")
    effect = trap.effect

    # -- Damage traps (pit, fire, gripping) --
    if trap.damage and trap.damage != "0":
        damage = roll_dice(trap.damage)
        # Ring of elements: halve fire damage
        if effect == "fire" and has_ring_effect(world, entity_id, "elements"):
            damage = damage // 2
        if health:
            actual = apply_damage(health, damage)
            events.append(TrapTriggered(
                entity=entity_id, damage=actual, trap_name=trap_name,
            ))
            events.append(MessageEvent(
                text=_msg("trap.triggered", world,
                          actor=entity_id, trap=trap_name,
                          damage=actual),
            ))

    # -- Poison: apply Poison component --
    if effect == "poison":
        if not world.has_component(entity_id, "Poison"):
            world.add_component(
                entity_id, "Poison",
                Poison(damage_per_turn=1, turns_remaining=5),
            )
        events.append(MessageEvent(
            text=_msg("trap.poison", world, actor=entity_id),
        ))

    # -- Paralysis: freeze in place --
    elif effect == "paralysis":
        status = world.get_component(entity_id, "StatusEffect")
        if status is None:
            status = StatusEffect()
            world.add_component(entity_id, "StatusEffect", status)
        status.paralyzed = max(status.paralyzed, 3)
        events.append(MessageEvent(
            text=_msg("trap.paralysis", world, actor=entity_id),
        ))

    # -- Gripping: damage + web --
    elif effect == "gripping":
        status = world.get_component(entity_id, "StatusEffect")
        if status is None:
            status = StatusEffect()
            world.add_component(entity_id, "StatusEffect", status)
        status.webbed = max(status.webbed, 3)
        events.append(MessageEvent(
            text=_msg("trap.gripping", world, actor=entity_id),
        ))

    # -- Fire: damage already applied, add message --
    elif effect == "fire":
        events.append(MessageEvent(
            text=_msg("trap.fire", world, actor=entity_id),
        ))

    # -- Alarm: alert all creatures on the level --
    elif effect == "alarm":
        pos = world.get_component(entity_id, "Position")
        if pos:
            for mid, ai, mpos in world.query("AI", "Position"):
                if mpos and mid != entity_id:
                    ai.behavior = "aggressive_melee"
        events.append(MessageEvent(
            text=_msg("trap.alarm", world, actor=entity_id),
        ))

    # -- Teleport: warp to a random floor tile --
    elif effect == "teleport":
        from nhc.dungeon.model import Terrain
        from nhc.utils.rng import get_rng
        rng = get_rng()
        pos = world.get_component(entity_id, "Position")
        if pos:
            floors = []
            for ty in range(level.height):
                for tx in range(level.width):
                    tile = level.tile_at(tx, ty)
                    if (tile and tile.terrain == Terrain.FLOOR
                            and not tile.feature):
                        floors.append((tx, ty))
            if floors:
                nx, ny = rng.choice(floors)
                pos.x = nx
                pos.y = ny
        events.append(MessageEvent(
            text=_msg("trap.teleport", world, actor=entity_id),
        ))

    # -- Summoning: spawn 1-2 hostile creatures nearby --
    elif effect == "summoning":
        from nhc.dungeon.model import Terrain
        from nhc.dungeon.populator import CREATURE_POOLS
        from nhc.entities.components import BlocksMovement as BM
        from nhc.entities.registry import EntityRegistry
        from nhc.utils.rng import get_rng
        rng = get_rng()
        difficulty = min(max(1, level.depth), max(CREATURE_POOLS.keys()))
        pool = CREATURE_POOLS.get(difficulty, CREATURE_POOLS[1])
        c_ids, c_weights = zip(*pool) if pool else ([], [])

        pos = world.get_component(entity_id, "Position")
        count = rng.randint(1, 2)
        summoned = 0
        if pos and c_ids:
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    if summoned >= count:
                        break
                    sx, sy = pos.x + dx, pos.y + dy
                    tile = level.tile_at(sx, sy)
                    if not tile or tile.terrain != Terrain.FLOOR:
                        continue
                    # Check no blocking entity there
                    blocked = False
                    for _, _, bp in world.query("BlocksMovement", "Position"):
                        if bp and bp.x == sx and bp.y == sy:
                            blocked = True
                            break
                    if blocked:
                        continue
                    cid = rng.choices(
                        list(c_ids), weights=list(c_weights), k=1,
                    )[0]
                    comps = EntityRegistry.get_creature(cid)
                    comps["BlocksMovement"] = BM()
                    comps["Position"] = Position(
                        x=sx, y=sy, level_id=pos.level_id,
                    )
                    world.create_entity(comps)
                    summoned += 1
                if summoned >= count:
                    break
        events.append(MessageEvent(
            text=_msg("trap.summoning", world, actor=entity_id),
        ))

    # -- Arrow: damage + flavor message --
    elif effect == "arrow":
        events.append(MessageEvent(
            text=_msg("trap.arrow", world, actor=entity_id),
        ))

    # -- Darts: damage (3d4) + flavor message --
    elif effect == "darts":
        events.append(MessageEvent(
            text=_msg("trap.darts", world, actor=entity_id),
        ))

    # -- Falling stone: damage + stun (paralyzed 1 turn) --
    elif effect == "falling_stone":
        status = world.get_component(entity_id, "StatusEffect")
        if status is None:
            status = StatusEffect()
            world.add_component(entity_id, "StatusEffect", status)
        status.paralyzed = max(status.paralyzed, 1)
        events.append(MessageEvent(
            text=_msg("trap.falling_stone", world, actor=entity_id),
        ))

    # -- Hallucinogenic spores: confusion --
    elif effect == "spores":
        status = world.get_component(entity_id, "StatusEffect")
        if status is None:
            status = StatusEffect()
            world.add_component(entity_id, "StatusEffect", status)
        status.confused = max(status.confused, 5)
        events.append(MessageEvent(
            text=_msg("trap.spores", world, actor=entity_id),
        ))

    # -- Trapdoor: damage + fall to next level --
    elif effect == "trapdoor":
        from nhc.core.events import LevelEntered
        events.append(MessageEvent(
            text=_msg("trap.trapdoor", world, actor=entity_id),
        ))
        events.append(LevelEntered(
            entity=entity_id,
            level_id=level.id,
            depth=level.depth + 1,
            fell=True,
        ))

    # -- Default: damage-only trap (pit) -- already handled above --

    return events
