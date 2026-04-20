"""Per-turn status effect processors.

These functions were extracted from Game to reduce game.py size.
Each takes the Game instance as first argument for access to
world, player_id, level, and renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.i18n import t
from nhc.rules.combat import apply_damage, heal, is_dead

# Hunger state thresholds
_SATIATED_THRESHOLD = 1000
_HUNGRY_THRESHOLD = 300
_STARVING_THRESHOLD = 100

if TYPE_CHECKING:
    from nhc.core.game import Game


def _creature_name(game: Game, eid: int) -> str:
    desc = game.world.get_component(eid, "Description")
    return desc.name if desc else "?"


def tick_poison(game: Game) -> None:
    """Apply ongoing poison damage and decrement counters."""
    expired = []
    for eid, poison, health in game.world.query("Poison", "Health"):
        if health is None:
            continue
        actual = apply_damage(health, poison.damage_per_turn)
        desc = game.world.get_component(eid, "Description")
        name = desc.name if desc else "?"
        game.renderer.add_message(
            t("combat.poison_tick", target=name, damage=actual),
        )
        if is_dead(health):
            if eid == game.player_id:
                game.killed_by = "poison"
            else:
                game.world.destroy_entity(eid)
        else:
            poison.turns_remaining -= 1
            if poison.turns_remaining <= 0:
                expired.append(eid)
    for eid in expired:
        game.world.remove_component(eid, "Poison")


def tick_regeneration(game: Game) -> None:
    """Troll-like regeneration: heal hp_per_turn if not fire-damaged."""
    for eid, regen, health in game.world.query("Regeneration", "Health"):
        if health is None:
            continue
        if regen.fire_damaged:
            regen.fire_damaged = False  # reset flag; no heal this turn
            continue
        healed = heal(health, regen.hp_per_turn)
        if healed > 0:
            game.renderer.add_message(
                t("combat.regenerates", creature=_creature_name(game, eid)),
            )


def tick_mummy_rot(game: Game) -> None:
    """Mummy rot curse: tick Cursed components and drain 1 max HP when due."""
    for eid, cursed, health in game.world.query("Cursed", "Health"):
        if health is None:
            continue
        cursed.ticks_until_drain -= 1
        if cursed.ticks_until_drain <= 0:
            if health.maximum > 1:
                health.maximum -= 1
                health.current = min(health.current, health.maximum)
                game.renderer.add_message(
                    t("combat.rot_drain",
                      target=_creature_name(game, eid)),
                )
            cursed.ticks_until_drain = 2


def tick_rings(game: Game) -> None:
    """Apply passive ring effects each turn."""
    equip = game.world.get_component(game.player_id, "Equipment")
    if not equip:
        return
    for slot in ("ring_left", "ring_right"):
        eid = getattr(equip, slot)
        if eid is None:
            continue
        ring = game.world.get_component(eid, "Ring")
        if not ring:
            continue

        if ring.effect == "mending" and game.turn % 5 == 0:
            health = game.world.get_component(
                game.player_id, "Health",
            )
            if health and health.current < health.maximum:
                health.current = min(
                    health.current + 1, health.maximum,
                )

        if ring.effect == "haste":
            status = game.world.get_component(
                game.player_id, "StatusEffect",
            )
            if status is None:
                from nhc.entities.components import StatusEffect
                status = StatusEffect(hasted=1)
                game.world.add_component(
                    game.player_id, "StatusEffect", status,
                )
            else:
                status.hasted = 1

        if ring.effect == "detection":
            # Auto-reveal traps and secret doors in FOV
            for y in range(game.level.height):
                for x in range(game.level.width):
                    tile = game.level.tile_at(x, y)
                    if not tile or not tile.visible:
                        continue
                    if tile.feature == "door_secret":
                        tile.feature = "door_closed"
                    for eid2, trap, tpos in game.world.query(
                        "Trap", "Position",
                    ):
                        if (tpos and tpos.x == x and tpos.y == y
                                and trap.hidden):
                            trap.hidden = False


def tick_stairs_proximity(game: Game) -> None:
    """Pre-generate next floor when player approaches downstairs.

    Scans visible downstairs tiles within PREFETCH_DISTANCE of the
    player and kicks off background generation for the next depth.
    """
    PREFETCH_DISTANCE = 7

    # Skip if already prefetching or if next depth is cached
    if game._prefetch_thread is not None:
        return
    next_depth = game.level.depth + 1
    if next_depth in game._floor_cache:
        return
    if game._prefetch_depth == next_depth:
        return  # already prefetched this depth

    pos = game.world.get_component(game.player_id, "Position")
    if not pos:
        return

    # Scan for downstairs within range
    for y in range(game.level.height):
        for x in range(game.level.width):
            tile = game.level.tile_at(x, y)
            if not tile or tile.feature != "stairs_down":
                continue
            dist = max(abs(x - pos.x), abs(y - pos.y))
            if dist <= PREFETCH_DISTANCE:
                game._start_prefetch(next_depth)
                return


DOOR_CLOSE_TURNS = 20
TRAP_REACTIVATE_TURNS = 40


def tick_doors(game: Game) -> None:
    """Auto-close doors that have been open for 20+ turns.

    Skips entirely when no doors are eligible, avoiding the cost
    of building an occupied-position set every turn.
    """
    level = game.level

    # Collect open doors that have been open long enough
    candidates: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tile_at(x, y)
            if (tile
                    and tile.feature == "door_open"
                    and tile.opened_at_turn is not None
                    and game.turn - tile.opened_at_turn
                    >= DOOR_CLOSE_TURNS):
                candidates.append((x, y))

    if not candidates:
        return

    # Build occupied set only when needed
    occupied: set[tuple[int, int]] = set()
    for _, pos in game.world.query("Position"):
        if pos is not None:
            occupied.add((pos.x, pos.y))

    for x, y in candidates:
        if (x, y) not in occupied:
            tile = level.tiles[y][x]
            tile.feature = "door_closed"
            tile.opened_at_turn = None
            if tile.visible:
                game.renderer.add_message(
                    t("explore.door_closes"))
            _sync_linked_door(game, x, y)


def _sync_linked_door(game: Game, x: int, y: int) -> None:
    """Propagate a door state change to the mirrored tile of any
    :class:`InteriorDoorLink` that touches ``(x, y)``.

    Safe no-op when the current level isn't a building floor or
    when there is no active site (dungeon mode).
    """
    site = getattr(game, "_active_site", None)
    if site is None:
        return
    bid = getattr(game.level, "building_id", None)
    if bid is None:
        return
    from nhc.dungeon.site import sync_linked_door_state
    sync_linked_door_state(site, bid, (x, y))


def tick_traps(game: Game) -> None:
    """Reactivate lair traps that were triggered 40+ turns ago."""
    for eid, trap, _ in game.world.query("Trap", "Position"):
        if (trap.reactivatable
                and trap.triggered
                and trap.triggered_at_turn is not None
                and game.turn - trap.triggered_at_turn
                >= TRAP_REACTIVATE_TURNS):
            trap.triggered = False
            trap.hidden = True
            trap.triggered_at_turn = None


def tick_wand_recharge(game: Game) -> None:
    """Recharge wands in inventory over time."""
    inv = game.world.get_component(game.player_id, "Inventory")
    if not inv:
        return
    for item_id in inv.slots:
        wand = game.world.get_component(item_id, "Wand")
        if not wand or wand.charges >= wand.max_charges:
            continue
        wand.recharge_timer -= 1
        if wand.recharge_timer <= 0:
            wand.charges += 1
            wand.recharge_timer = 20


def _hunger_state(current: int) -> str:
    """Derive hunger state from current satiation."""
    if current > _SATIATED_THRESHOLD:
        return "satiated"
    if current > _HUNGRY_THRESHOLD:
        return "normal"
    if current > _STARVING_THRESHOLD:
        return "hungry"
    return "starving"


def tick_hunger(game: Game) -> None:
    """Decrement player hunger each turn and apply effects."""
    hunger = game.world.get_component(game.player_id, "Hunger")
    if not hunger:
        return

    hunger.current = max(0, hunger.current - 1)
    state = _hunger_state(hunger.current)

    # State transition messages
    prev = hunger.prev_state
    if state != prev:
        if prev in ("normal", "satiated") and state == "hungry":
            game.renderer.add_message(t("hunger.getting_hungry"))
        elif state == "starving":
            game.renderer.add_message(t("hunger.starving"))
        elif prev == "satiated" and state == "normal":
            game.renderer.add_message(t("hunger.no_longer_full"))
        hunger.prev_state = state

    # Apply / remove stat penalties
    if state == "hungry":
        hunger.str_penalty = -1
        hunger.dex_penalty = -1
    elif state == "starving":
        hunger.str_penalty = -2
        hunger.dex_penalty = -2
    else:
        hunger.str_penalty = 0
        hunger.dex_penalty = 0

    # Satiated: minor HP regen every 20 turns
    if state == "satiated" and game.turn % 20 == 0:
        health = game.world.get_component(game.player_id, "Health")
        if health and health.current < health.maximum:
            heal(health, 1)

    # Starving: HP damage every 5 turns
    if state == "starving" and game.turn % 5 == 0:
        health = game.world.get_component(game.player_id, "Health")
        if health:
            apply_damage(health, 1)
            game.renderer.add_message(t("hunger.starving_damage"))
