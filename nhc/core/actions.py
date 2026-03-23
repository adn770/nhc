"""Action resolution pipeline."""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from nhc.core.events import (
    CreatureAttacked,
    CreatureDied,
    DoorOpened,
    Event,
    GameWon,
    ItemPickedUp,
    ItemUsed,
    MessageEvent,
    TrapTriggered,
)
from nhc.entities.components import (
    AI,
    BloodDrain,
    BlocksMovement,
    Consumable,
    Cursed,
    Description,
    DisenchantTouch,
    Enchanted,
    Equipment,
    FrostBreath,
    Health,
    Inventory,
    LootTable,
    MummyRot,
    PetrifyingTouch,
    Poison,
    Position,
    Renderable,
    RequiresMagicWeapon,
    Stats,
    StatusEffect,
    Trap,
    Undead,
    Weapon,
)
from nhc.i18n import t
from nhc.rules.combat import apply_damage, heal, is_dead, resolve_melee_attack
from nhc.rules.loot import generate_loot
from nhc.utils.rng import d20, roll_dice
from nhc.utils.spatial import adjacent

if TYPE_CHECKING:
    from nhc.core.ecs import EntityId, World
    from nhc.dungeon.model import Level


class Action(abc.ABC):
    """Base action. All player/creature actions inherit from this."""

    def __init__(self, actor: int) -> None:
        self.actor = actor

    @abc.abstractmethod
    async def validate(self, world: "World", level: "Level") -> bool:
        """Check if this action is valid in the current state."""

    @abc.abstractmethod
    async def execute(self, world: "World", level: "Level") -> list[Event]:
        """Perform the action, returning resulting events."""


class WaitAction(Action):
    """Do nothing, pass the turn."""

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return []


class MoveAction(Action):
    """Move in a direction."""

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)
        if not tile:
            return False
        if tile.feature == "door_closed":
            return True
        return tile.walkable

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)

        # Auto-open closed doors
        if tile.feature == "door_closed":
            tile.feature = "door_open"
            events.append(DoorOpened(entity=self.actor, x=nx, y=ny))
            events.append(MessageEvent(
                text=_msg("explore.open_door", world, actor=self.actor),
            ))
            return events

        # Check for blocking creatures at target
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                return []

        # Move
        pos.x = nx
        pos.y = ny

        # Check for traps
        events += _check_traps(world, level, self.actor, nx, ny)

        # Announce items on ground (player only)
        if world.has_component(self.actor, "Player"):
            events += _announce_ground_items(world, nx, ny, self.actor)

        return events


class MeleeAttackAction(Action):
    """Melee attack against a target."""

    def __init__(self, actor: int, target: int) -> None:
        super().__init__(actor)
        self.target = target

    async def validate(self, world: "World", level: "Level") -> bool:
        apos = world.get_component(self.actor, "Position")
        tpos = world.get_component(self.target, "Position")
        if not apos or not tpos:
            return False
        return adjacent(apos.x, apos.y, tpos.x, tpos.y)

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []

        a_stats = world.get_component(self.actor, "Stats")
        t_stats = world.get_component(self.target, "Stats")
        t_health = world.get_component(self.target, "Health")

        if not a_stats or not t_stats or not t_health:
            return events

        attacker_name = _entity_name(world, self.actor)
        target_name = _entity_name(world, self.target)

        # PetrifyingGaze: attacker must save DEX 12 or be paralyzed
        if world.has_component(self.target, "PetrifyingGaze"):
            if d20() + a_stats.dexterity < 12:
                a_status = world.get_component(self.actor, "StatusEffect")
                if a_status is None:
                    world.add_component(
                        self.actor, "StatusEffect",
                        StatusEffect(paralyzed=9),
                    )
                else:
                    a_status.paralyzed = 9
                events.append(MessageEvent(
                    text=_msg("combat.petrified", world,
                              target=self.actor),
                ))
                return events
            events.append(MessageEvent(
                text=_msg("combat.petrify_saved", world,
                          target=self.actor),
            ))

        # Invisible target: attacker misses automatically
        t_status_pre = world.get_component(self.target, "StatusEffect")
        if t_status_pre and t_status_pre.invisible > 0:
            events.append(MessageEvent(
                text=_msg("combat.miss_invisible", world,
                          target=self.target),
            ))
            return events

        # Get weapon damage: inline Weapon (creatures) > equipped Weapon (player)
        weapon_damage = "1d4"  # Unarmed fallback
        inline_wpn = world.get_component(self.actor, "Weapon")
        if inline_wpn:
            weapon_damage = inline_wpn.damage
        else:
            equip = world.get_component(self.actor, "Equipment")
            if equip and equip.weapon is not None:
                wpn = world.get_component(equip.weapon, "Weapon")
                if wpn:
                    weapon_damage = wpn.damage

        hit, damage = resolve_melee_attack(a_stats, t_stats, weapon_damage)
        logger.debug(
            "Melee: %s→%s wpn=%s hit=%s dmg=%d",
            attacker_name, target_name, weapon_damage, hit, damage,
        )

        # RequiresMagicWeapon: non-enchanted weapons deal 0 damage
        if hit and world.has_component(self.target, "RequiresMagicWeapon"):
            weapon_is_magic = False
            if inline_wpn:
                weapon_is_magic = world.has_component(self.actor, "Enchanted")
            else:
                equip = world.get_component(self.actor, "Equipment")
                if equip and equip.weapon is not None:
                    weapon_is_magic = world.has_component(equip.weapon, "Enchanted")
            if not weapon_is_magic:
                events.append(MessageEvent(
                    text=_msg("combat.magic_weapon_needed", world,
                              target=self.target),
                ))
                hit = False
                damage = 0

        # Blessed attacker: +1 damage on a hit
        a_status = world.get_component(self.actor, "StatusEffect")
        if hit and a_status and a_status.blessed > 0:
            damage += 1

        # Sleeping targets are auto-hit and wake on damage
        t_status = world.get_component(self.target, "StatusEffect")
        if t_status and t_status.sleeping > 0:
            t_status.sleeping = 0
            hit = True

        # Mirror images absorb hits before real damage
        if hit and t_status and t_status.mirror_images > 0:
            t_status.mirror_images -= 1
            events.append(MessageEvent(
                text=_msg("combat.mirror_absorbed", world,
                          target=self.target,
                          remaining=t_status.mirror_images),
            ))
            return events

        if hit:
            actual = apply_damage(t_health, damage)
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=actual, hit=True,
            ))
            events.append(MessageEvent(
                text=_msg("combat.hit", world,
                          actor=self.actor, target=self.target,
                          damage=actual),
            ))

            # Attacking while invisible breaks the effect
            if a_status and a_status.invisible > 0:
                a_status.invisible = 0

            # DrainTouch: drain XP and reduce max HP on player
            if world.has_component(self.actor, "DrainTouch"):
                player = world.get_component(self.target, "Player")
                if player and t_health.maximum > 1:
                    t_health.maximum = max(1, t_health.maximum - 1)
                    t_health.current = min(t_health.current, t_health.maximum)
                    player.xp = max(0, player.xp - 5)
                    events.append(MessageEvent(
                        text=_msg("combat.drained", world,
                                  actor=self.actor, target=self.target),
                    ))

            # VenomousStrike: apply poison on hit
            if world.has_component(self.actor, "VenomousStrike"):
                if not world.has_component(self.target, "Poison"):
                    world.add_component(
                        self.target, "Poison",
                        Poison(damage_per_turn=1, turns_remaining=3),
                    )
                    events.append(MessageEvent(
                        text=_msg("combat.poisoned", world,
                                  target=self.target),
                    ))

            # BloodDrain: drain HP and heal self
            bd = world.get_component(self.actor, "BloodDrain")
            if bd:
                drain = bd.drain_per_hit
                drain_actual = apply_damage(t_health, drain)
                a_health = world.get_component(self.actor, "Health")
                if a_health:
                    heal(a_health, drain)
                events.append(MessageEvent(
                    text=_msg("combat.blood_drain", world,
                              actor=self.actor, target=self.target,
                              damage=drain_actual),
                ))

            # PetrifyingTouch: target saves DEX 12 or paralyzed
            if world.has_component(self.actor, "PetrifyingTouch"):
                if d20() + t_stats.dexterity < 12:
                    if t_status is None:
                        world.add_component(
                            self.target, "StatusEffect",
                            StatusEffect(paralyzed=9),
                        )
                    else:
                        t_status.paralyzed = 9
                    events.append(MessageEvent(
                        text=_msg("combat.petrify_touch", world,
                                  target=self.target),
                    ))

            # FrostBreath: extra cold damage on hit
            fb = world.get_component(self.actor, "FrostBreath")
            if fb:
                cold = roll_dice(fb.dice)
                cold_actual = apply_damage(t_health, cold)
                events.append(MessageEvent(
                    text=_msg("combat.frost_breath", world,
                              actor=self.actor, target=self.target,
                              damage=cold_actual),
                ))

            # CharmTouch: charm the target (like dryad)
            if world.has_component(self.actor, "CharmTouch"):
                if not world.has_component(self.target, "Undead"):
                    if t_status is None:
                        world.add_component(
                            self.target, "StatusEffect",
                            StatusEffect(charmed=9),
                        )
                    else:
                        t_status.charmed = 9
                    events.append(MessageEvent(
                        text=_msg("combat.charm_touch", world,
                                  target=self.target),
                    ))

            # MummyRot: curse the target with a slow HP-draining rot
            if world.has_component(self.actor, "MummyRot"):
                if not world.has_component(self.target, "Cursed"):
                    world.add_component(
                        self.target, "Cursed", Cursed(ticks_until_drain=2),
                    )
                    events.append(MessageEvent(
                        text=_msg("combat.mummy_rot", world,
                                  target=self.target),
                    ))

            # DisenchantTouch: destroy one consumable in target's inventory
            if world.has_component(self.actor, "DisenchantTouch"):
                t_inv = world.get_component(self.target, "Inventory")
                if t_inv:
                    magic_items = [
                        eid for eid in t_inv.slots
                        if world.has_component(eid, "Consumable")
                    ]
                    if magic_items:
                        from nhc.utils.rng import roll_dice as _rd
                        chosen = magic_items[0]
                        c_desc = world.get_component(chosen, "Description")
                        c_name = c_desc.name if c_desc else "item"
                        t_inv.slots.remove(chosen)
                        world.destroy_entity(chosen)
                        events.append(MessageEvent(
                            text=_msg("combat.disenchant", world,
                                      actor=self.actor, target=self.target,
                                      item=c_name),
                        ))

            if is_dead(t_health):
                logger.info(
                    "%s killed %s (actor=%d, target=%d)",
                    attacker_name, target_name, self.actor, self.target,
                )
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                ))
                events.append(MessageEvent(
                    text=_msg("combat.slain", world,
                              actor=self.actor, target=self.target),
                ))

                # Drop loot before destroying
                tpos = world.get_component(self.target, "Position")
                loot = world.get_component(self.target, "LootTable")
                if loot and tpos:
                    dropped = generate_loot(
                        world, loot, tpos.x, tpos.y, tpos.level_id,
                    )
                    if dropped:
                        names = []
                        for did in dropped:
                            d = world.get_component(did, "Description")
                            if d:
                                names.append(d.name)
                        if names:
                            events.append(MessageEvent(
                                text=_msg("combat.drops", world,
                                          target=self.target,
                                          items=", ".join(names)),
                            ))

                # Leave a corpse marker, then destroy
                if tpos:
                    corpse_name = t("combat.corpse", name=target_name)
                    world.create_entity({
                        "Position": Position(
                            x=tpos.x, y=tpos.y, level_id=tpos.level_id,
                        ),
                        "Renderable": Renderable(
                            glyph="%", color="bright_red", render_order=0,
                        ),
                        "Description": Description(
                            name=corpse_name,
                            short=corpse_name,
                        ),
                    })

                # Don't destroy the player entity — let the game loop
                # handle player death (supports god mode HP restore).
                if not world.has_component(self.target, "Player"):
                    world.destroy_entity(self.target)
        else:
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=0, hit=False,
            ))
            events.append(MessageEvent(
                text=_msg("combat.miss", world,
                          actor=self.actor, target=self.target),
            ))

        return events


class PickupItemAction(Action):
    """Pick up an item from the ground."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item
        self.full = False

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv:
            return False
        # Gold never needs an inventory slot
        is_gold = world.has_component(self.item, "Gold")
        if not is_gold and len(inv.slots) >= inv.max_slots:
            self.full = True
            return False
        item_pos = world.get_component(self.item, "Position")
        actor_pos = world.get_component(self.actor, "Position")
        if not item_pos or not actor_pos:
            return False
        return item_pos.x == actor_pos.x and item_pos.y == actor_pos.y

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []

        # Gold goes straight into the Player.gold purse
        if world.has_component(self.item, "Gold"):
            return self._pickup_gold(world, events)

        inv = world.get_component(self.actor, "Inventory")
        inv.slots.append(self.item)
        # Remove position so it's no longer on the map
        world.add_component(self.item, "Position", None)

        item_name = _entity_name(world, self.item)
        events.append(ItemPickedUp(entity=self.actor, item=self.item))
        events.append(MessageEvent(
            text=t("item.picked_up", item=item_name),
        ))

        return events

class EquipAction(Action):
    """Equip a weapon or shield from inventory."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item not in inv.slots:
            return False
        # Must be a weapon or shield
        return (world.has_component(self.item, "Weapon")
                or world.has_component(self.item, "Shield"))

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        equip = world.get_component(self.actor, "Equipment")
        if not equip:
            return events

        item_name = _entity_name(world, self.item)

        # Unequip current weapon if equipping a weapon
        if world.has_component(self.item, "Weapon"):
            if equip.weapon is not None and equip.weapon != self.item:
                old_name = _entity_name(world, equip.weapon)
                events.append(MessageEvent(
                    text=t("item.unequipped", item=old_name),
                ))
            equip.weapon = self.item

        events.append(MessageEvent(
            text=t("item.equipped", item=item_name),
        ))
        return events


class DropAction(Action):
    """Drop an item from inventory onto the floor."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        return inv is not None and self.item in inv.slots

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")
        pos = world.get_component(self.actor, "Position")

        item_name = _entity_name(world, self.item)

        # Unequip if currently equipped
        equip = world.get_component(self.actor, "Equipment")
        if equip and equip.weapon == self.item:
            equip.weapon = None

        # Remove from inventory
        if self.item in inv.slots:
            inv.slots.remove(self.item)

        # Place on the map at player's position
        if pos:
            world.add_component(self.item, "Position", Position(
                x=pos.x, y=pos.y, level_id=pos.level_id,
            ))

        events.append(MessageEvent(
            text=t("item.dropped", item=item_name),
        ))
        return events


    def _pickup_gold(
        self, world: "World", events: list[Event],
    ) -> list[Event]:
        """Absorb gold into the player's purse and destroy the entity."""
        import re

        desc = world.get_component(self.item, "Description")
        name = desc.name if desc else "Gold"

        # Extract numeric quantity from name (e.g. "12 Gold" → 12)
        match = re.match(r"(\d+)", name)
        amount = int(match.group(1)) if match else 1

        player = world.get_component(self.actor, "Player")
        if player:
            player.gold += amount

        events.append(ItemPickedUp(entity=self.actor, item=self.item))
        events.append(MessageEvent(
            text=t("item.gold_picked_up", amount=amount),
        ))

        world.destroy_entity(self.item)
        return events


class UseItemAction(Action):
    """Use a consumable item from inventory."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item not in inv.slots:
            return False
        consumable = world.get_component(self.item, "Consumable")
        return consumable is not None

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")
        consumable = world.get_component(self.item, "Consumable")
        item_name = _entity_name(world, self.item)

        consumed = True

        if consumable.effect == "heal":
            health = world.get_component(self.actor, "Health")
            if health:
                if health.current >= health.maximum:
                    events.append(MessageEvent(
                        text=t("item.full_health"),
                    ))
                    return events
                amount = roll_dice(consumable.dice)
                actual = heal(health, amount)
                events.append(ItemUsed(
                    entity=self.actor, item=self.item, effect="heal",
                ))
                events.append(MessageEvent(
                    text=t("item.quaff_heal", item=item_name,
                           amount=actual),
                ))

        elif consumable.effect == "strength":
            stats = world.get_component(self.actor, "Stats")
            if stats:
                stats.strength += 1
                events.append(ItemUsed(
                    entity=self.actor, item=self.item, effect="strength",
                ))
                events.append(MessageEvent(
                    text=t("item.strength_up"),
                ))

        elif consumable.effect == "frost":
            # Freeze visible creatures (paralyzed for N turns)
            events.append(MessageEvent(text=t("item.frost_cast")))
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
                                        StatusEffect(paralyzed=duration))
                else:
                    status.paralyzed = duration
                name = _entity_name(world, eid)
                events.append(MessageEvent(
                    text=t("item.frost_affects", target=name),
                ))
            events.append(ItemUsed(
                entity=self.actor, item=self.item, effect="frost",
            ))

        elif consumable.effect == "damage_nearest":
            events += _use_damage_nearest(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "sleep":
            events += _use_sleep(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "magic_missile":
            events += _use_magic_missile(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "hold_person":
            events += _use_hold_person(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "fireball":
            events += _use_fireball(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "web":
            events += _use_web(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "charm_person":
            events += _use_charm_person(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "bless":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "blessed",
                t("item.bless_cast"), t("item.bless_active"),
            )

        elif consumable.effect == "mirror_image":
            events += _use_mirror_image(
                world, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "invisibility":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "invisible",
                t("item.invis_cast"), t("item.invis_active"),
            )

        elif consumable.effect == "haste":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "hasted",
                t("item.haste_cast"), t("item.haste_active"),
            )

        elif consumable.effect == "protection_evil":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "protected",
                t("item.protect_cast"), t("item.protect_active"),
            )

        elif consumable.effect == "detect_magic":
            events += _use_detect_magic(world, level, self.actor, self.item)

        elif consumable.effect == "detect_evil":
            events += _use_detect_evil(world, level, self.actor, self.item)

        elif consumable.effect == "detect_invisibility":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "infravision",
                t("item.detect_invis_cast"), t("item.detect_invis_active"),
            )

        elif consumable.effect == "find_traps":
            events += _use_find_traps(world, level, self.actor, self.item)

        elif consumable.effect == "light":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "infravision",
                t("item.light_cast"), t("item.light_active"),
            )

        elif consumable.effect == "remove_fear":
            events += _use_remove_fear(world, self.actor, self.item)

        elif consumable.effect == "shield":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "shielded",
                t("item.shield_cast"), t("item.shield_active"),
            )

        elif consumable.effect == "resist_cold":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "resist_cold",
                t("item.resist_cold_cast"), t("item.resist_cold_active"),
            )

        elif consumable.effect == "resist_fire":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "resist_fire",
                t("item.resist_fire_cast"), t("item.resist_fire_active"),
            )

        elif consumable.effect == "levitate":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "levitating",
                t("item.levitate_cast"), t("item.levitate_active"),
            )

        elif consumable.effect == "fly":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "flying",
                t("item.fly_cast"), t("item.fly_active"),
            )

        elif consumable.effect == "dispel_magic":
            events += _use_dispel_magic(
                world, level, self.actor, self.item,
            )

        elif consumable.effect == "protection_missiles":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "prot_missiles",
                t("item.prot_missiles_cast"),
                t("item.prot_missiles_active"),
            )

        elif consumable.effect == "silence":
            events += _use_silence(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "phantasmal_force":
            events += _use_phantasmal_force(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "clairvoyance":
            events += _use_clairvoyance(world, level, self.actor, self.item)

        elif consumable.effect == "infravision":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "infravision",
                t("item.infravision_cast"), t("item.infravision_active"),
            )

        elif consumable.effect == "continual_light":
            events += _use_continual_light(world, self.actor, self.item)

        elif consumable.effect == "water_breathing":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "water_breathing",
                t("item.water_breathing_cast"),
                t("item.water_breathing_active"),
            )

        elif consumable.effect == "charm_snakes":
            events += _use_charm_snakes(
                world, level, self.actor, self.item, consumable, item_name,
            )

        else:
            events.append(MessageEvent(
                text=t("item.nothing_happens"),
            ))
            consumed = False

        if not consumed:
            return events

        # Remove item from inventory and world
        if self.item in inv.slots:
            inv.slots.remove(self.item)
        # Unequip if it was equipped
        equip = world.get_component(self.actor, "Equipment")
        if equip and equip.weapon == self.item:
            equip.weapon = None
        world.destroy_entity(self.item)

        return events


class DescendStairsAction(Action):
    """Descend to the next dungeon level."""

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x, pos.y)
        return tile is not None and tile.feature == "stairs_down"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.core.events import LevelEntered
        return [
            LevelEntered(
                entity=self.actor,
                level_id=level.id,
                depth=level.depth + 1,
            ),
            MessageEvent(text=t("explore.descend")),
        ]


class LookAction(Action):
    """Examine the current tile and surroundings."""

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return events

        tile = level.tile_at(pos.x, pos.y)

        # Describe tile feature
        if tile and tile.feature:
            fname = t(f"feature.{tile.feature}")
            # Fallback to raw feature name if no translation
            if fname == f"feature.{tile.feature}":
                fname = tile.feature
            events.append(MessageEvent(
                text=t("explore.see_feature", feature=fname),
            ))

        # Describe items on tile
        items = _items_at(world, pos.x, pos.y, self.actor)
        for eid in items:
            desc = world.get_component(eid, "Description")
            if desc and desc.long:
                events.append(MessageEvent(text=desc.long))
            elif desc:
                events.append(MessageEvent(
                    text=t("explore.see_item", item=desc.short),
                ))

        # Describe visible creatures
        for eid, _, cpos in world.query("AI", "Position"):
            if cpos is None:
                continue
            ctile = level.tile_at(cpos.x, cpos.y)
            if ctile and ctile.visible:
                desc = world.get_component(eid, "Description")
                health = world.get_component(eid, "Health")
                if desc:
                    hp_desc = ""
                    if health:
                        pct = health.current / health.maximum
                        if pct >= 1.0:
                            hp_desc = t("health_status.uninjured")
                        elif pct > 0.5:
                            hp_desc = t("health_status.lightly_wounded")
                        elif pct > 0.25:
                            hp_desc = t("health_status.badly_wounded")
                        else:
                            hp_desc = t("health_status.near_death")
                    events.append(MessageEvent(
                        text=t("explore.see_creature",
                               creature=desc.short, status=hp_desc),
                    ))

        if not events:
            events.append(MessageEvent(text=t("explore.nothing_special")))

        return events


class SearchAction(Action):
    """Search adjacent tiles for hidden traps and secret doors.

    Uses a WIS check: d20 + WIS bonus vs DC of each hidden feature.
    """

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return events

        stats = world.get_component(self.actor, "Stats")
        wis_bonus = stats.wisdom if stats else 0
        found = 0

        # Check current tile and all 8 adjacent tiles
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                tx, ty = pos.x + dx, pos.y + dy

                # Check for hidden traps (entities)
                for eid, trap, tpos in world.query("Trap", "Position"):
                    if tpos is None:
                        continue
                    if tpos.x == tx and tpos.y == ty and trap.hidden:
                        roll_val = d20()
                        if roll_val + wis_bonus >= trap.dc:
                            trap.hidden = False
                            desc = world.get_component(eid, "Description")
                            name = desc.name if desc else "trap"
                            events.append(MessageEvent(
                                text=t("explore.search_found_trap",
                                       trap=name),
                            ))
                            found += 1

                # Check for secret doors (tile feature)
                tile = level.tile_at(tx, ty)
                if tile and tile.feature == "door_secret":
                    roll_val = d20()
                    if roll_val + wis_bonus >= 12:
                        tile.feature = "door_closed"
                        events.append(MessageEvent(
                            text=t("explore.search_found_door"),
                        ))
                        found += 1

        if found == 0:
            events.append(MessageEvent(
                text=t("explore.search_nothing"),
            ))

        return events


class CustomAction(Action):
    """Freeform TTRPG action resolved as an ability check."""

    def __init__(self, actor: int, description: str = "",
                 ability: str = "wisdom", dc: int = 12) -> None:
        super().__init__(actor)
        self.description = description
        self.ability = ability
        self.dc = dc

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.core.events import CustomActionEvent

        stats = world.get_component(self.actor, "Stats")
        bonus = getattr(stats, self.ability, 0) if stats else 0
        roll_val = d20()
        total = roll_val + bonus
        success = total >= self.dc

        event = CustomActionEvent(
            description=self.description,
            ability=self.ability,
            roll=roll_val,
            bonus=bonus,
            dc=self.dc,
            success=success,
        )
        return [event]


class ImpossibleAction(Action):
    """The LLM determined the player's intent is not possible."""

    def __init__(self, actor: int, reason: str = "") -> None:
        super().__init__(actor)
        self.reason = reason

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return [MessageEvent(text=self.reason)]


class BumpAction(Action):
    """Smart directional action: attack, open door, or move."""

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    def resolve(self, world: "World", level: "Level") -> Action | None:
        """Convert bump into a concrete action."""
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return None
        nx, ny = pos.x + self.dx, pos.y + self.dy

        # Check for creature at target: attack
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                return MeleeAttackAction(actor=self.actor, target=eid)

        # Otherwise: move (handles doors internally)
        return MoveAction(actor=self.actor, dx=self.dx, dy=self.dy)

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        resolved = self.resolve(world, level)
        if resolved is None:
            return []
        if await resolved.validate(world, level):
            return await resolved.execute(world, level)
        return []


# ── Helpers ──────────────────────────────────────────────────────────


def _entity_name(world: "World", eid: int) -> str:
    """Get raw display name for an entity (no article)."""
    desc = world.get_component(eid, "Description")
    if desc and desc.name:
        return desc.name
    player = world.get_component(eid, "Player")
    if player is not None:
        return t("game.player_name")
    return "something"


def _is_player(world: "World", eid: int) -> bool:
    """Check if an entity is the player."""
    return world.has_component(eid, "Player")


_CATALAN_VOWELS = set("aeiouàèéíòóúh")


def _det_name(world: "World", eid: int) -> str:
    """Get display name with article for Romance languages.

    For Catalan/Spanish, prepends el/la/l' based on grammatical gender.
    For English or entities without gender, returns the raw name.
    """
    from nhc.i18n import current_lang

    desc = world.get_component(eid, "Description")
    if not desc or not desc.name:
        player = world.get_component(eid, "Player")
        if player is not None:
            return t("game.player_name")
        return "something"

    name = desc.name
    gender = desc.gender
    lang = current_lang()

    if not gender or lang == "en":
        return name

    lower = name.lower()
    if lang == "ca":
        if lower[0] in _CATALAN_VOWELS:
            return f"l'{lower}"
        return f"el {lower}" if gender == "m" else f"la {lower}"
    elif lang == "es":
        if gender == "m":
            return f"el {lower}"
        return f"la {lower}"

    return name


def _msg(
    key: str,
    world: "World",
    *,
    actor: int | None = None,
    target: int | None = None,
    **kwargs: object,
) -> str:
    """Build a message, selecting player-aware variant if available.

    For Romance languages (Catalan, Spanish), combat messages need different
    verb conjugations when the player is involved. This helper selects:
      - "you_{leaf}" variant when the player is the actor
      - "{leaf}_you" variant when the player is the target
      - the base key as fallback (3rd person)

    Entity names are inserted with articles for Romance languages, and the
    first character of the result is capitalized.
    """
    section, leaf = key.rsplit(".", 1)
    actor_is_player = actor is not None and _is_player(world, actor)
    target_is_player = target is not None and _is_player(world, target)

    # Build kwargs with article-aware entity names
    kw = dict(**kwargs)
    if actor is not None:
        name = _det_name(world, actor)
        kw["attacker"] = name
        kw["actor"] = name
        kw["entity"] = name
    if target is not None:
        kw["target"] = _det_name(world, target)

    # Try player-specific variant first
    if actor_is_player:
        variant = f"{section}.you_{leaf}"
        result = t(variant, **kw)
        if result != variant:
            return _capitalize_first(result)
    elif target_is_player:
        variant = f"{section}.{leaf}_you"
        result = t(variant, **kw)
        if result != variant:
            return _capitalize_first(result)

    return _capitalize_first(t(key, **kw))


def _capitalize_first(s: str) -> str:
    """Capitalize the first character, handling elided articles like l'."""
    if not s:
        return s
    if len(s) >= 3 and s[1] == "'":
        # "l'esquelet" → "L'esquelet"
        return s[0].upper() + s[1:]
    return s[0].upper() + s[1:]


def _items_at(
    world: "World", x: int, y: int, exclude: int = -1,
) -> list[int]:
    """Find item entities at a given position."""
    items: list[int] = []
    for eid, _, ipos in world.query("Description", "Position"):
        if ipos is None or eid == exclude:
            continue
        if ipos.x == x and ipos.y == y:
            if (not world.has_component(eid, "AI")
                    and not world.has_component(eid, "BlocksMovement")
                    and not world.has_component(eid, "Trap")):
                items.append(eid)
    return items


def _announce_ground_items(
    world: "World", x: int, y: int, actor: int,
) -> list[Event]:
    """Generate messages for items lying on the ground at position."""
    items = _items_at(world, x, y, exclude=actor)
    if not items:
        return []

    events: list[Event] = []
    if len(items) == 1:
        desc = world.get_component(items[0], "Description")
        name = (desc.short or desc.name) if desc else "something"
        events.append(MessageEvent(
            text=t("explore.see_item", item=name),
        ))
    else:
        names = []
        for eid in items:
            desc = world.get_component(eid, "Description")
            names.append(desc.name if desc else "???")
        events.append(MessageEvent(
            text=t("explore.see_items", count=len(items),
                   items=", ".join(names)),
        ))
    return events


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

        # DEX save vs trap DC
        stats = world.get_component(entity_id, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        save_roll = d20()

        entity_name = _entity_name(world, entity_id)
        trap_desc = world.get_component(eid, "Description")
        trap_name = trap_desc.name if trap_desc else "a trap"

        if save_roll + dex_bonus >= trap.dc:
            events.append(MessageEvent(
                text=_msg("trap.avoided", world,
                          actor=entity_id, trap=trap_name),
            ))
        else:
            damage = roll_dice(trap.damage)
            health = world.get_component(entity_id, "Health")
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

        trap.triggered = True
        trap.hidden = False

    return events


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
            world.add_component(eid, "StatusEffect", StatusEffect(sleeping=9))
        else:
            status.sleeping = 9
        name = _entity_name(world, eid)
        events.append(MessageEvent(text=t("item.sleep_affects", target=name)))
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
    from nhc.utils.spatial import chebyshev
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
        events.append(ItemUsed(entity=actor, item=item, effect="magic_missile"))
        events.append(MessageEvent(
            text=t("item.missile_hits", target=target_name, damage=actual),
        ))
        if is_dead(target_health):
            events.append(CreatureDied(entity=best_eid, killer=actor))
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
    from nhc.utils.rng import get_rng
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
        events.append(MessageEvent(text=t("item.hold_affects", target=name)))

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
    dead_eids = []

    for eid in targets:
        health = world.get_component(eid, "Health")
        if not health:
            continue
        stats = world.get_component(eid, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        dmg = max(1, base_damage // 2) if d20() + dex_bonus >= 12 else base_damage
        actual = apply_damage(health, dmg)
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.fireball_hits", target=name, damage=actual),
        ))
        if is_dead(health):
            dead_eids.append(eid)

    events.append(ItemUsed(entity=actor, item=item, effect="fireball"))

    for eid in dead_eids:
        events.append(CreatureDied(entity=eid, killer=actor))
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
    from nhc.utils.spatial import chebyshev
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
            events.append(CreatureDied(entity=best_eid, killer=actor))
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
            world.add_component(eid, "StatusEffect", StatusEffect(webbed=duration))
        else:
            status.webbed = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(text=t("item.web_caught", target=name)))
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
    """Charm the nearest visible non-undead humanoid for consumable.dice turns."""
    from nhc.utils.spatial import chebyshev
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
        world.add_component(best_eid, "StatusEffect", StatusEffect(charmed=duration))
    else:
        status.charmed = duration

    name = _entity_name(world, best_eid)
    events.append(MessageEvent(text=t("item.charm_affects", target=name)))
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
        world.add_component(actor, "StatusEffect", StatusEffect(**{field: duration}))
    else:
        setattr(status, field, duration)

    events.append(MessageEvent(text=cast_msg))
    events.append(MessageEvent(text=active_msg))
    events.append(ItemUsed(entity=actor, item=item, effect=consumable.effect))
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
    events.append(MessageEvent(text=t("item.mirror_images", count=count)))
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

    events.append(ItemUsed(entity=actor, item=item, effect="phantasmal_force"))
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
    events.append(ItemUsed(entity=actor, item=item, effect="continual_light"))
    return events


def _use_charm_snakes(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Pacify serpent-type creatures (serp_gegant, home_serp, etc.)."""
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


class BansheeWailAction(Action):
    """Banshee wail: every humanoid in range must save CON or die."""

    def __init__(self, actor: int, player_id: int) -> None:
        super().__init__(actor)
        self.player_id = player_id

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.utils.spatial import chebyshev

        events: list[Event] = []
        attacker_name = _entity_name(world, self.actor)
        events.append(MessageEvent(
            text=t("combat.banshee_wail", creature=attacker_name),
        ))

        wail = world.get_component(self.actor, "DeathWail")
        if not wail:
            return events

        a_pos = world.get_component(self.actor, "Position")
        if not a_pos:
            return events

        p_pos = world.get_component(self.player_id, "Position")
        p_stats = world.get_component(self.player_id, "Stats")
        p_health = world.get_component(self.player_id, "Health")
        if p_pos and p_stats and p_health:
            dist = chebyshev(a_pos.x, a_pos.y, p_pos.x, p_pos.y)
            if dist <= wail.radius:
                if d20() + p_stats.constitution < wail.save_dc:
                    p_health.current = 0
                    events.append(MessageEvent(
                        text=_msg("combat.banshee_kills", world,
                                  target=self.player_id),
                    ))
                    events.append(CreatureDied(
                        entity=self.player_id, killer=self.actor,
                    ))
                else:
                    events.append(MessageEvent(
                        text=_msg("combat.banshee_saved", world,
                                  target=self.player_id),
                    ))
        return events


class ShriekAction(Action):
    """Shrieker emits a piercing shriek that wakes all sleeping creatures."""

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        attacker_name = _entity_name(world, self.actor)
        events.append(MessageEvent(
            text=t("combat.shrieker_shriek", creature=attacker_name),
        ))
        # Wake all sleeping creatures on this level
        for eid, status, _ in world.query("StatusEffect", "Position"):
            if status and status.sleeping > 0:
                status.sleeping = 0
                name = _entity_name(world, eid)
                events.append(MessageEvent(
                    text=t("combat.shriek_wakes", creature=name),
                ))
        return events
