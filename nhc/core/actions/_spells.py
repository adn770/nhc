"""Spell/consumable effect handler functions (_use_* helpers)."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nhc.core.actions._helpers import _entity_name, _msg
from nhc.core.events import CreatureDied, Event, ItemUsed, MessageEvent
from nhc.dungeon.model import Terrain
from nhc.entities.components import Poison, StatusEffect
from nhc.i18n import t
from nhc.rules.combat import apply_damage, is_dead
from nhc.utils.rng import d20, get_rng, roll_dice
from nhc.utils.spatial import chebyshev

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.entities.components import Consumable


def _use_sleep(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Put visible creatures to sleep (2d8 total HD, weakest first)."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.sleep_cast")))

    total_hd = roll_dice(consumable.dice)

    # Gather visible AI creatures, sorted by HP ascending (weakest first)
    candidates: list[tuple[int, int]] = []
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        health = world.get_component(eid, "Health")
        if health:
            candidates.append((health.current, eid))
    candidates.sort()

    hd_spent = 0
    affected = 0
    for hp, eid in candidates:
        if hd_spent >= total_hd:
            break
        health = world.get_component(eid, "Health")
        hd = max(1, health.maximum // 4)
        if hd_spent + hd > total_hd:
            break
        hd_spent += hd
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect",
                                StatusEffect(sleeping=9))
        else:
            status.sleeping = 9
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.sleep_affects", target=name),
        ))
        affected += 1

    if affected == 0:
        events.append(MessageEvent(text=t("item.sleep_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="sleep"))
    return events


def _use_magic_missile(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Auto-hit the nearest visible creature for 1d6+1."""
    events: list[Event] = []

    apos = world.get_component(actor, "Position")
    if not apos:
        return events

    best_eid = None
    best_dist = 999
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if tile and tile.visible:
            dist = chebyshev(apos.x, apos.y, cpos.x, cpos.y)
            if dist < best_dist:
                best_dist = dist
                best_eid = eid

    if best_eid is None:
        events.append(MessageEvent(text=t("item.no_target")))
        return events

    damage = roll_dice(consumable.dice)
    target_health = world.get_component(best_eid, "Health")
    target_name = _entity_name(world, best_eid)

    if target_health:
        actual = apply_damage(target_health, damage)
        events.append(ItemUsed(
            entity=actor, item=item, effect="magic_missile",
        ))
        events.append(MessageEvent(
            text=t("item.missile_hits", target=target_name, damage=actual),
        ))
        if is_dead(target_health):
            events.append(CreatureDied(
                entity=best_eid, killer=actor,
                max_hp=target_health.maximum,
            ))
            events.append(MessageEvent(
                text=_msg("combat.slain", world,
                          actor=actor, target=best_eid),
            ))
            world.destroy_entity(best_eid)

    return events


def _use_hold_person(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Paralyze 1d4 visible humanoids for consumable.dice turns."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.hold_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = 9

    humanoids = []
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        humanoids.append(eid)

    if not humanoids:
        events.append(MessageEvent(text=t("item.hold_no_humanoids")))
        return events

    count = min(roll_dice("1d4"), len(humanoids))
    targets = get_rng().sample(humanoids, count)

    for eid in targets:
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(
                eid, "StatusEffect", StatusEffect(paralyzed=duration),
            )
        else:
            status.paralyzed = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.hold_affects", target=name),
        ))

    events.append(ItemUsed(entity=actor, item=item, effect="hold_person"))
    return events


def _use_fireball(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Hit all visible creatures for 3d6 (DEX save for half)."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.fireball_cast")))

    targets = []
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if tile and tile.visible:
            targets.append(eid)

    if not targets:
        events.append(MessageEvent(text=t("item.no_target")))
        return events

    base_damage = roll_dice(consumable.dice)
    dead_eids: list[tuple[int, int]] = []  # (eid, max_hp)

    for eid in targets:
        health = world.get_component(eid, "Health")
        if not health:
            continue
        stats = world.get_component(eid, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        dmg = (max(1, base_damage // 2)
               if d20() + dex_bonus >= 12 else base_damage)
        actual = apply_damage(health, dmg)
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.fireball_hits", target=name, damage=actual),
        ))
        if is_dead(health):
            dead_eids.append((eid, health.maximum))

    events.append(ItemUsed(entity=actor, item=item, effect="fireball"))

    for eid, max_hp in dead_eids:
        events.append(CreatureDied(
            entity=eid, killer=actor, max_hp=max_hp,
        ))
        events.append(MessageEvent(
            text=_msg("combat.slain", world, actor=actor, target=eid),
        ))
        world.destroy_entity(eid)

    return events


def _use_damage_nearest(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Damage the nearest visible creature."""
    events: list[Event] = []

    apos = world.get_component(actor, "Position")
    if not apos:
        return events

    # Find nearest creature with AI
    best_eid = None
    best_dist = 999
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if tile and tile.visible:
            dist = chebyshev(apos.x, apos.y, cpos.x, cpos.y)
            if dist < best_dist:
                best_dist = dist
                best_eid = eid

    if best_eid is None:
        events.append(MessageEvent(text=t("item.no_target")))
        return events

    damage = roll_dice(consumable.dice)
    target_health = world.get_component(best_eid, "Health")
    target_name = _entity_name(world, best_eid)

    if target_health:
        actual = apply_damage(target_health, damage)
        events.append(ItemUsed(
            entity=actor, item=item, effect="damage_nearest",
        ))
        events.append(MessageEvent(
            text=t("item.lightning_strike", item=item_name,
                   target=target_name, damage=actual),
        ))

        if is_dead(target_health):
            events.append(CreatureDied(
                entity=best_eid, killer=actor,
                max_hp=target_health.maximum,
            ))
            events.append(MessageEvent(
                text=_msg("combat.destroyed", world,
                          actor=actor, target=best_eid),
            ))
            world.destroy_entity(best_eid)

    return events


def _use_web(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Entangle all visible creatures for consumable.dice turns."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.web_cast")))

    duration = roll_dice(consumable.dice)
    affected = 0

    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect",
                                StatusEffect(webbed=duration))
        else:
            status.webbed = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.web_caught", target=name),
        ))
        affected += 1

    if affected == 0:
        events.append(MessageEvent(text=t("item.no_target")))

    events.append(ItemUsed(entity=actor, item=item, effect="web"))
    return events


def _use_charm_person(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Charm the nearest visible non-undead humanoid."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.charm_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = 9

    apos = world.get_component(actor, "Position")
    if not apos:
        return events

    best_eid = None
    best_dist = 999
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        dist = chebyshev(apos.x, apos.y, cpos.x, cpos.y)
        if dist < best_dist:
            best_dist = dist
            best_eid = eid

    if best_eid is None:
        events.append(MessageEvent(text=t("item.charm_no_target")))
        return events

    status = world.get_component(best_eid, "StatusEffect")
    if status is None:
        world.add_component(best_eid, "StatusEffect",
                            StatusEffect(charmed=duration))
    else:
        status.charmed = duration

    name = _entity_name(world, best_eid)
    events.append(MessageEvent(
        text=t("item.charm_affects", target=name),
    ))
    events.append(ItemUsed(entity=actor, item=item, effect="charm_person"))
    return events


def _use_self_buff(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
    field: str,
    cast_msg: str,
    active_msg: str,
) -> list[Event]:
    """Apply a self-targeted buff (blessed/invisible/hasted/protected)."""
    events: list[Event] = []
    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = roll_dice(consumable.dice)

    status = world.get_component(actor, "StatusEffect")
    if status is None:
        world.add_component(actor, "StatusEffect",
                            StatusEffect(**{field: duration}))
    else:
        setattr(status, field, duration)

    events.append(MessageEvent(text=cast_msg))
    events.append(MessageEvent(text=active_msg))
    events.append(ItemUsed(entity=actor, item=item,
                           effect=consumable.effect))
    return events


def _use_mirror_image(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Create 1d4 illusory duplicates; each absorbs one incoming hit."""
    events: list[Event] = []
    count = roll_dice(consumable.dice)

    status = world.get_component(actor, "StatusEffect")
    if status is None:
        world.add_component(actor, "StatusEffect",
                            StatusEffect(mirror_images=count))
    else:
        status.mirror_images = count

    events.append(MessageEvent(text=t("item.mirror_cast")))
    events.append(MessageEvent(
        text=t("item.mirror_images", count=count),
    ))
    events.append(ItemUsed(entity=actor, item=item, effect="mirror_image"))
    return events


def _use_detect_magic(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
) -> list[Event]:
    """Reveal all magic items (consumables) on the current level."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.detect_magic_cast")))

    count = 0
    for eid, _, ipos in world.query("Consumable", "Position"):
        if ipos is None:
            continue
        tile = level.tile_at(ipos.x, ipos.y)
        if tile:
            tile.explored = True
            count += 1

    if count:
        events.append(MessageEvent(
            text=t("item.detect_magic_reveal", count=count),
        ))
    else:
        events.append(MessageEvent(text=t("item.detect_magic_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="detect_magic"))
    return events


def _use_detect_evil(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
) -> list[Event]:
    """Reveal hostile creatures on the current level."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.detect_evil_cast")))

    count = 0
    for eid, ai, cpos in world.query("AI", "Position"):
        if cpos is None or ai is None:
            continue
        if ai.behavior in ("aggressive_melee",):
            tile = level.tile_at(cpos.x, cpos.y)
            if tile:
                tile.explored = True
                tile.visible = True
                count += 1

    if count:
        events.append(MessageEvent(
            text=t("item.detect_evil_reveal", count=count),
        ))
    else:
        events.append(MessageEvent(text=t("item.detect_evil_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="detect_evil"))
    return events


def _use_find_traps(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
) -> list[Event]:
    """Reveal all hidden traps on the level."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.find_traps_cast")))

    count = 0
    for eid, trap, tpos in world.query("Trap", "Position"):
        if trap.hidden:
            trap.hidden = False
            count += 1

    if count:
        events.append(MessageEvent(
            text=t("item.find_traps_reveal", count=count),
        ))
    else:
        events.append(MessageEvent(text=t("item.find_traps_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="find_traps"))
    return events


def _use_remove_fear(
    world: "World",
    actor: int,
    item: int,
) -> list[Event]:
    """Remove paralysis and fear effects from the player."""
    events: list[Event] = []
    status = world.get_component(actor, "StatusEffect")
    if status:
        status.paralyzed = 0
        status.sleeping = 0

    events.append(MessageEvent(text=t("item.remove_fear_cast")))
    events.append(MessageEvent(text=t("item.remove_fear_active")))
    events.append(ItemUsed(entity=actor, item=item, effect="remove_fear"))
    return events


def _use_acid(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
) -> list[Event]:
    """Acid potion: self-damage + cure petrification/paralysis."""
    events: list[Event] = []
    damage = roll_dice(consumable.dice)
    health = world.get_component(actor, "Health")
    if health:
        actual = apply_damage(health, damage)
        events.append(MessageEvent(
            text=t("item.acid_quaff", damage=actual),
        ))

    # Cure petrification / paralysis
    status = world.get_component(actor, "StatusEffect")
    if status and status.paralyzed > 0:
        status.paralyzed = 0
        events.append(MessageEvent(
            text=t("item.acid_cures"),
        ))

    events.append(ItemUsed(entity=actor, item=item, effect="acid"))
    return events


def _use_sickness(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
) -> list[Event]:
    """Sickness potion: self-damage + poison."""
    events: list[Event] = []
    damage = roll_dice(consumable.dice)
    health = world.get_component(actor, "Health")
    if health:
        actual = apply_damage(health, damage)
        events.append(MessageEvent(
            text=t("item.sickness_quaff", damage=actual),
        ))

    world.add_component(
        actor, "Poison",
        Poison(damage_per_turn=1, turns_remaining=5),
    )
    events.append(MessageEvent(
        text=t("item.sickness_poison"),
    ))
    events.append(ItemUsed(entity=actor, item=item, effect="sickness"))
    return events


def _use_dispel_magic(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
) -> list[Event]:
    """Strip all status effects from visible creatures."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.dispel_cast")))

    affected = 0
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        status = world.get_component(eid, "StatusEffect")
        if status:
            world.remove_component(eid, "StatusEffect")
            name = _entity_name(world, eid)
            events.append(MessageEvent(
                text=t("item.dispel_affects", target=name),
            ))
            affected += 1

    if affected == 0:
        events.append(MessageEvent(text=t("item.dispel_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="dispel_magic"))
    return events


def _use_silence(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Silence visible creatures (prevents scroll use)."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.silence_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = roll_dice(consumable.dice)

    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect",
                                StatusEffect(silenced=duration))
        else:
            status.silenced = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.silence_affects", target=name),
        ))

    events.append(ItemUsed(entity=actor, item=item, effect="silence"))
    return events


def _use_phantasmal_force(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Confuse visible enemies."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.phantasmal_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = roll_dice(consumable.dice)

    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect",
                                StatusEffect(confused=duration))
        else:
            status.confused = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.phantasmal_affects", target=name),
        ))

    events.append(ItemUsed(entity=actor, item=item,
                           effect="phantasmal_force"))
    return events


def _use_clairvoyance(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
) -> list[Event]:
    """Reveal map tiles in a large radius around the player."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.clairvoyance_cast")))

    pos = world.get_component(actor, "Position")
    if pos:
        radius = 12
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    tile = level.tile_at(pos.x + dx, pos.y + dy)
                    if tile:
                        tile.explored = True

    events.append(MessageEvent(text=t("item.clairvoyance_reveal")))
    events.append(ItemUsed(entity=actor, item=item, effect="clairvoyance"))
    return events


def _use_continual_light(
    world: "World",
    actor: int,
    item: int,
) -> list[Event]:
    """Create a permanent light (very long duration infravision)."""
    events: list[Event] = []
    # 999 turns is effectively permanent for a dungeon level
    status = world.get_component(actor, "StatusEffect")
    if status is None:
        world.add_component(actor, "StatusEffect",
                            StatusEffect(infravision=999))
    else:
        status.infravision = 999

    events.append(MessageEvent(text=t("item.continual_light_cast")))
    events.append(ItemUsed(entity=actor, item=item,
                           effect="continual_light"))
    return events


def _use_charm_snakes(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Pacify serpent-type creatures."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.charm_snakes_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = roll_dice(consumable.dice)

    serpent_ids = {"giant_snake", "snakeman"}
    affected = 0
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        desc = world.get_component(eid, "Description")
        # Check by matching known serpent creature names
        creature_name = desc.name.lower() if desc else ""
        is_serpent = any(
            kw in creature_name
            for kw in ("serp", "snake", "serpent", "cobra", "víbria")
        )
        if not is_serpent:
            continue
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect",
                                StatusEffect(charmed=duration))
        else:
            status.charmed = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.charm_snakes_affects", target=name),
        ))
        affected += 1

    if affected == 0:
        events.append(MessageEvent(text=t("item.charm_snakes_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="charm_snakes"))
    return events


def _use_enchant_weapon(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
) -> list[Event]:
    """Permanently +1 to wielded weapon, cap +3, risk above."""
    events: list[Event] = []
    equip = world.get_component(actor, "Equipment")
    if not equip or equip.weapon is None:
        events.append(MessageEvent(
            text=t("item.enchant_weapon_no_weapon"),
        ))
        return events

    wpn_id = equip.weapon
    wpn = world.get_component(wpn_id, "Weapon")
    wpn_name = _entity_name(world, wpn_id)
    if not wpn:
        events.append(MessageEvent(
            text=t("item.enchant_weapon_no_weapon"),
        ))
        return events

    if wpn.magic_bonus >= 3:
        # Over-enchant: 50% chance of destruction
        if d20() <= 10:
            events.append(MessageEvent(
                text=t("item.enchant_weapon_destroy", item=wpn_name),
            ))
            equip.weapon = None
            inv = world.get_component(actor, "Inventory")
            if inv and wpn_id in inv.slots:
                inv.slots.remove(wpn_id)
            world.destroy_entity(wpn_id)
        else:
            events.append(MessageEvent(
                text=t("item.nothing_happens"),
            ))
    else:
        wpn.magic_bonus += 1
        events.append(MessageEvent(
            text=t("item.enchant_weapon_success", item=wpn_name,
                   bonus=wpn.magic_bonus),
        ))

    events.append(ItemUsed(entity=actor, item=item,
                           effect="enchant_weapon"))
    return events


def _use_enchant_armor(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
) -> list[Event]:
    """Permanently +1 to worn armor, cap +3, risk above."""
    events: list[Event] = []
    equip = world.get_component(actor, "Equipment")
    if not equip or equip.armor is None:
        events.append(MessageEvent(
            text=t("item.enchant_armor_no_armor"),
        ))
        return events

    arm_id = equip.armor
    arm = world.get_component(arm_id, "Armor")
    arm_name = _entity_name(world, arm_id)
    if not arm:
        events.append(MessageEvent(
            text=t("item.enchant_armor_no_armor"),
        ))
        return events

    if arm.magic_bonus >= 3:
        if d20() <= 10:
            events.append(MessageEvent(
                text=t("item.enchant_armor_destroy", item=arm_name),
            ))
            equip.armor = None
            inv = world.get_component(actor, "Inventory")
            if inv and arm_id in inv.slots:
                inv.slots.remove(arm_id)
            world.destroy_entity(arm_id)
        else:
            events.append(MessageEvent(
                text=t("item.nothing_happens"),
            ))
    else:
        arm.magic_bonus += 1
        events.append(MessageEvent(
            text=t("item.enchant_armor_success", item=arm_name,
                   bonus=arm.magic_bonus),
        ))

    events.append(ItemUsed(entity=actor, item=item,
                           effect="enchant_armor"))
    return events


def _use_charging(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
) -> list[Event]:
    """Restore charges to the first wand in inventory."""
    events: list[Event] = []
    inv = world.get_component(actor, "Inventory")
    if not inv:
        events.append(MessageEvent(text=t("item.charging_no_wand")))
        return events

    # Find first wand in inventory
    wand_id = None
    for slot_id in inv.slots:
        if world.has_component(slot_id, "Wand"):
            wand_id = slot_id
            break

    if wand_id is None:
        events.append(MessageEvent(text=t("item.charging_no_wand")))
        return events

    wand = world.get_component(wand_id, "Wand")
    restored = roll_dice(consumable.dice)
    wand.charges = min(wand.charges + restored, wand.max_charges)
    wand_name = _entity_name(world, wand_id)
    events.append(MessageEvent(
        text=t("item.charging_success", item=wand_name),
    ))
    events.append(ItemUsed(entity=actor, item=item, effect="charging"))
    return events


def _use_teleport_self(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
) -> list[Event]:
    """Teleport the actor to a random floor tile."""

    events: list[Event] = []
    pos = world.get_component(actor, "Position")
    if not pos:
        events.append(MessageEvent(text=t("item.nothing_happens")))
        return events

    floors = []
    for ty in range(level.height):
        for tx in range(level.width):
            tile = level.tile_at(tx, ty)
            if (tile and tile.terrain == Terrain.FLOOR
                    and not tile.feature):
                floors.append((tx, ty))

    if floors:
        nx, ny = random.choice(floors)
        pos.x = nx
        pos.y = ny

    events.append(MessageEvent(text=t("item.teleport_self")))
    events.append(ItemUsed(entity=actor, item=item, effect="teleport"))
    return events
