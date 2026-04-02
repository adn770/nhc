"""Per-turn status effect processors.

These functions were extracted from Game to reduce game.py size.
Each takes the Game instance as first argument for access to
world, player_id, level, and renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.i18n import t
from nhc.rules.combat import apply_damage, heal, is_dead

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
