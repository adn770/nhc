"""Item pickup, equip, unequip, drop, and use actions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import (
    _count_slots_used,
    _entity_name,
    _item_slot_cost,
)
from nhc.core.events import Event, ItemPickedUp, ItemUsed, MessageEvent
from nhc.entities.components import Position, StatusEffect
from nhc.i18n import t
from nhc.rules.combat import heal
from nhc.utils.rng import get_rng, roll_dice

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


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
        if not is_gold:
            # Sum actual slot costs (weapons/armor use multiple)
            used = _count_slots_used(world, inv)
            item_cost = _item_slot_cost(world, self.item)
            if used + item_cost > inv.max_slots:
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
        world.remove_component(self.item, "Position")

        item_name = _entity_name(world, self.item)
        events.append(ItemPickedUp(entity=self.actor, item=self.item))
        events.append(MessageEvent(
            text=t("item.picked_up", item=item_name),
        ))

        return events

    def _pickup_gold(
        self, world: "World", events: list[Event],
    ) -> list[Event]:
        """Absorb gold into the player's purse and destroy the entity."""
        desc = world.get_component(self.item, "Description")
        name = desc.name if desc else "Gold"

        # Extract numeric quantity from name (e.g. "12 Gold" -> 12)
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


class EquipAction(Action):
    """Equip a weapon or armor piece from inventory."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item not in inv.slots:
            return False
        return (world.has_component(self.item, "Weapon")
                or world.has_component(self.item, "Armor")
                or world.has_component(self.item, "Ring"))

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        equip = world.get_component(self.actor, "Equipment")
        if not equip:
            return events

        item_name = _entity_name(world, self.item)

        if world.has_component(self.item, "Weapon"):
            if equip.weapon is not None and equip.weapon != self.item:
                old_name = _entity_name(world, equip.weapon)
                events.append(MessageEvent(
                    text=t("item.unequipped", item=old_name),
                ))
            equip.weapon = self.item

        armor = world.get_component(self.item, "Armor")
        if armor:
            slot_map = {"body": "armor", "shield": "shield",
                        "helmet": "helmet"}
            attr = slot_map.get(armor.slot, "armor")
            current = getattr(equip, attr, None)
            if current is not None and current != self.item:
                old_name = _entity_name(world, current)
                events.append(MessageEvent(
                    text=t("item.unequipped", item=old_name),
                ))
            setattr(equip, attr, self.item)

        ring = world.get_component(self.item, "Ring")
        if ring:
            # Fill left slot first, then right
            if equip.ring_left is None:
                equip.ring_left = self.item
            elif equip.ring_right is None:
                equip.ring_right = self.item
            else:
                # Both full -- swap left
                old_name = _entity_name(world, equip.ring_left)
                events.append(MessageEvent(
                    text=t("item.unequipped", item=old_name),
                ))
                equip.ring_left = self.item

        events.append(MessageEvent(
            text=t("item.equipped", item=item_name),
        ))
        return events


class UnequipAction(Action):
    """Unequip a currently equipped item."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        equip = world.get_component(self.actor, "Equipment")
        if not equip:
            return False
        return self.item in (equip.weapon, equip.armor,
                             equip.shield, equip.helmet,
                             equip.ring_left, equip.ring_right)

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        equip = world.get_component(self.actor, "Equipment")
        item_name = _entity_name(world, self.item)
        for attr in ("weapon", "armor", "shield", "helmet",
                      "ring_left", "ring_right"):
            if getattr(equip, attr) == self.item:
                setattr(equip, attr, None)
        return [MessageEvent(text=t("item.unequipped", item=item_name))]


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

        # Unequip if currently equipped (any slot)
        equip = world.get_component(self.actor, "Equipment")
        if equip:
            for attr in ("weapon", "armor", "shield", "helmet",
                        "ring_left", "ring_right"):
                if getattr(equip, attr) == self.item:
                    setattr(equip, attr, None)

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
        from nhc.core.actions._spells import (
            _use_acid,
            _use_charm_person,
            _use_charm_snakes,
            _use_charging,
            _use_clairvoyance,
            _use_continual_light,
            _use_damage_nearest,
            _use_detect_evil,
            _use_detect_magic,
            _use_dispel_magic,
            _use_enchant_armor,
            _use_enchant_weapon,
            _use_find_traps,
            _use_fireball,
            _use_hold_person,
            _use_magic_missile,
            _use_mirror_image,
            _use_phantasmal_force,
            _use_remove_fear,
            _use_self_buff,
            _use_sickness,
            _use_silence,
            _use_sleep,
            _use_teleport_self,
            _use_web,
        )

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

        elif consumable.effect == "satiate":
            hunger = world.get_component(self.actor, "Hunger")
            if hunger:
                amount = int(consumable.dice)
                hunger.current = min(hunger.maximum,
                                     hunger.current + amount)
            events.append(ItemUsed(
                entity=self.actor, item=self.item, effect="satiate",
            ))
            events.append(MessageEvent(
                text=t("item.eat", item=item_name),
            ))

        elif consumable.effect == "mushroom":
            hunger = world.get_component(self.actor, "Hunger")
            if hunger:
                amount = int(consumable.dice)
                hunger.current = min(hunger.maximum,
                                     hunger.current + amount)
            events.append(ItemUsed(
                entity=self.actor, item=self.item, effect="mushroom",
            ))
            events.append(MessageEvent(
                text=t("item.eat", item=item_name),
            ))
            roll = get_rng().random()
            if roll < 0.50:
                pass  # just food
            elif roll < 0.70:
                health = world.get_component(self.actor, "Health")
                if health:
                    actual = heal(health, roll_dice("1d4"))
                    events.append(MessageEvent(
                        text=t("item.mushroom_heal"),
                    ))
            elif roll < 0.85:
                from nhc.entities.components import Poison
                world.add_component(self.actor, "Poison",
                    Poison(damage_per_turn=1, turns_remaining=2))
                events.append(MessageEvent(
                    text=t("item.mushroom_poison"),
                ))
            else:
                status = world.get_component(self.actor, "StatusEffect")
                if status:
                    status.confused = 3
                events.append(MessageEvent(
                    text=t("item.mushroom_confuse"),
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

        elif consumable.effect == "identify":
            # Identify is handled specially in the game loop
            # (needs UI interaction to pick which item)
            events.append(ItemUsed(
                entity=self.actor, item=self.item, effect="identify",
            ))
            events.append(MessageEvent(
                text=t("item.identify_cast"),
            ))

        elif consumable.effect == "speed":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "hasted",
                t("item.speed_cast"), t("item.speed_active"),
            )

        elif consumable.effect == "confusion":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "confused",
                t("item.confusion_cast"), t("item.confusion_active"),
            )

        elif consumable.effect == "blindness":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "blinded",
                t("item.blindness_cast"), t("item.blindness_active"),
            )

        elif consumable.effect == "acid":
            events += _use_acid(
                world, self.actor, self.item, consumable,
            )

        elif consumable.effect == "sickness":
            events += _use_sickness(
                world, self.actor, self.item, consumable,
            )

        elif consumable.effect == "enchant_weapon":
            events += _use_enchant_weapon(
                world, self.actor, self.item, consumable,
            )

        elif consumable.effect == "enchant_armor":
            events += _use_enchant_armor(
                world, self.actor, self.item, consumable,
            )

        elif consumable.effect == "charging":
            events += _use_charging(
                world, self.actor, self.item, consumable,
            )

        elif consumable.effect == "teleport":
            events += _use_teleport_self(
                world, level, self.actor, self.item, consumable,
            )

        else:
            events.append(MessageEvent(
                text=t("item.nothing_happens"),
            ))
            consumed = False

        if not consumed:
            return events

        # Stamp real item ID on ItemUsed events for identification
        real_id = world.get_component(self.item, "_potion_id") or ""
        for ev in events:
            if isinstance(ev, ItemUsed) and not ev.item_id:
                ev.item_id = real_id

        # Remove item from inventory and world
        if self.item in inv.slots:
            inv.slots.remove(self.item)
        # Unequip if it was equipped
        equip = world.get_component(self.actor, "Equipment")
        if equip and equip.weapon == self.item:
            equip.weapon = None
        world.destroy_entity(self.item)

        return events
