"""Ranged actions: throw potions and zap wands."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import _entity_name
from nhc.core.events import (
    CreatureDied, DoorOpened, Event, ItemUsed, MessageEvent,
)
from nhc.dungeon.model import SurfaceType, Terrain
from nhc.entities.components import Poison, StatusEffect
from nhc.i18n import t
from nhc.rules.combat import apply_damage, heal as do_heal
from nhc.utils.rng import get_rng, roll_dice

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


class ThrowAction(Action):
    """Throw a potion at a target creature, applying its effect."""

    def __init__(self, actor: int, item: int, target: int) -> None:
        super().__init__(actor)
        self.item = item
        self.target = target

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item not in inv.slots:
            return False
        consumable = world.get_component(self.item, "Consumable")
        if not consumable:
            return False
        # Target must exist and be visible
        tpos = world.get_component(self.target, "Position")
        if not tpos:
            return False
        tile = level.tile_at(tpos.x, tpos.y)
        return tile is not None and tile.visible

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")
        consumable = world.get_component(self.item, "Consumable")
        item_name = _entity_name(world, self.item)
        target_name = _entity_name(world, self.target)

        events.append(MessageEvent(
            text=t("item.throw_at", item=item_name, target=target_name),
        ))

        # Apply the effect to the target
        effect = consumable.effect
        health = world.get_component(self.target, "Health")

        if effect == "heal" and health:
            amount = roll_dice(consumable.dice)
            do_heal(health, amount)

        elif effect in ("frost", "hold_person"):
            try:
                duration = int(consumable.dice)
            except ValueError:
                duration = roll_dice(consumable.dice)
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(
                    self.target, "StatusEffect",
                    StatusEffect(paralyzed=duration),
                )
            else:
                status.paralyzed = duration
            events.append(MessageEvent(
                text=t("item.frost_affects", target=target_name),
            ))

        elif effect == "fireball" and health:
            damage = roll_dice(consumable.dice)
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.fireball_hits", target=target_name,
                       damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "sleep":
            total_hd = roll_dice(consumable.dice)
            if not world.has_component(self.target, "Undead"):
                status = world.get_component(self.target, "StatusEffect")
                if status is None:
                    world.add_component(
                        self.target, "StatusEffect",
                        StatusEffect(sleeping=9),
                    )
                else:
                    status.sleeping = 9
                events.append(MessageEvent(
                    text=t("item.sleep_affects", target=target_name),
                ))

        elif effect == "invisibility":
            # Makes the TARGET invisible (confusing but fun)
            try:
                duration = int(consumable.dice)
            except ValueError:
                duration = roll_dice(consumable.dice)
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(
                    self.target, "StatusEffect",
                    StatusEffect(invisible=duration),
                )
            else:
                status.invisible = duration

        elif effect == "damage_nearest" and health:
            damage = roll_dice(consumable.dice)
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.lightning_strike", item=item_name,
                       target=target_name, damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "confusion":
            try:
                duration = int(consumable.dice)
            except ValueError:
                duration = roll_dice(consumable.dice)
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(
                    self.target, "StatusEffect",
                    StatusEffect(confused=duration),
                )
            else:
                status.confused = duration
            events.append(MessageEvent(
                text=t("item.confusion_affects", target=target_name),
            ))

        elif effect == "blindness":
            try:
                duration = int(consumable.dice)
            except ValueError:
                duration = roll_dice(consumable.dice)
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(
                    self.target, "StatusEffect",
                    StatusEffect(blinded=duration),
                )
            else:
                status.blinded = duration
            events.append(MessageEvent(
                text=t("item.blindness_affects", target=target_name),
            ))

        elif effect == "acid" and health:
            damage = roll_dice(consumable.dice)
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.acid_hits", target=target_name,
                       damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "sickness":
            world.add_component(
                self.target, "Poison",
                Poison(damage_per_turn=2, turns_remaining=5),
            )
            events.append(MessageEvent(
                text=t("item.sickness_affects", target=target_name),
            ))

        elif effect == "speed":
            try:
                duration = int(consumable.dice)
            except ValueError:
                duration = roll_dice(consumable.dice)
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(
                    self.target, "StatusEffect",
                    StatusEffect(hasted=duration),
                )
            else:
                status.hasted = duration
            events.append(MessageEvent(
                text=t("item.speed_affects", target=target_name),
            ))

        else:
            # Generic: just report the throw
            pass

        real_id = world.get_component(self.item, "_potion_id") or ""
        events.append(ItemUsed(
            entity=self.actor, item=self.item, effect=effect,
            item_id=real_id,
        ))

        # Remove from inventory and destroy potion
        if self.item in inv.slots:
            inv.slots.remove(self.item)
        world.destroy_entity(self.item)

        return events


class ZapAction(Action):
    """Zap a wand at a target creature, using one charge."""

    def __init__(self, actor: int, item: int, target: int) -> None:
        super().__init__(actor)
        self.item = item
        self.target = target

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item not in inv.slots:
            return False
        wand = world.get_component(self.item, "Wand")
        if not wand or wand.charges <= 0:
            return False
        tpos = world.get_component(self.target, "Position")
        if not tpos:
            return False
        tile = level.tile_at(tpos.x, tpos.y)
        return tile is not None and tile.visible

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        wand = world.get_component(self.item, "Wand")
        target_name = _entity_name(world, self.target)
        health = world.get_component(self.target, "Health")

        wand.charges -= 1

        effect = wand.effect

        if effect == "firebolt" and health:
            damage = roll_dice("2d6")
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.fireball_hits", target=target_name,
                       damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "lightning" and health:
            damage = roll_dice("3d4")
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.lightning_strike", item="wand",
                       target=target_name, damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "magic_missile" and health:
            damage = roll_dice("1d6+1")
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.missile_hits", target=target_name,
                       damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "disintegrate" and health:
            damage = roll_dice("3d6")
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.fireball_hits", target=target_name,
                       damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "teleport":
            # Move target to a random floor tile
            floors = []
            for ty in range(level.height):
                for tx in range(level.width):
                    tile = level.tile_at(tx, ty)
                    if (tile and tile.terrain.name == "FLOOR"
                            and not tile.feature
                            and tile.surface_type != SurfaceType.CORRIDOR):
                        floors.append((tx, ty))
            if floors:
                nx, ny = get_rng().choice(floors)
                tpos = world.get_component(self.target, "Position")
                if tpos:
                    tpos.x = nx
                    tpos.y = ny
            events.append(MessageEvent(
                text=t("item.nothing_happens"),
            ))

        elif effect == "poison":
            world.add_component(self.target, "Poison",
                                Poison(damage_per_turn=2, turns_remaining=5))
            events.append(MessageEvent(
                text=t("combat.poisoned", target=target_name),
            ))

        elif effect == "slowness":
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(self.target, "StatusEffect",
                                    StatusEffect(webbed=8))
            else:
                status.webbed = 8
            events.append(MessageEvent(
                text=t("item.web_caught", target=target_name),
            ))

        elif effect == "amok":
            status = world.get_component(self.target, "StatusEffect")
            if status is None:
                world.add_component(self.target, "StatusEffect",
                                    StatusEffect(confused=6))
            else:
                status.confused = 6
            events.append(MessageEvent(
                text=t("item.phantasmal_affects", target=target_name),
            ))

        elif effect == "cold" and health:
            damage = roll_dice("2d6")
            actual = apply_damage(health, damage)
            events.append(MessageEvent(
                text=t("item.cold_hits", target=target_name,
                       damage=actual),
            ))
            if health.current <= 0:
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "death":
            ai = world.get_component(self.target, "AI")
            faction = ai.faction if ai else ""
            immune = faction in ("undead", "demon")
            if immune:
                events.append(MessageEvent(
                    text=t("item.death_ray_immune", target=target_name),
                ))
            elif health:
                health.current = 0
                events.append(MessageEvent(
                    text=t("item.death_ray", target=target_name),
                ))
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                    max_hp=health.maximum,
                ))

        elif effect == "cancellation":
            status = world.get_component(self.target, "StatusEffect")
            if status:
                world.remove_component(self.target, "StatusEffect")
                events.append(MessageEvent(
                    text=t("item.cancel_affects", target=target_name),
                ))
            else:
                events.append(MessageEvent(
                    text=t("item.cancel_no_effects",
                           target=target_name),
                ))

        elif effect == "opening":
            tpos = world.get_component(self.target, "Position")
            if tpos:
                tile = level.tile_at(tpos.x, tpos.y)
                if tile and tile.feature in ("door_closed",
                                             "door_locked"):
                    tile.feature = "door_open"
                    events.append(DoorOpened(
                        entity=self.actor, x=tpos.x, y=tpos.y))
                    events.append(MessageEvent(
                        text=t("item.wand_open_door"),
                    ))
                else:
                    events.append(MessageEvent(
                        text=t("item.wand_no_door"),
                    ))

        elif effect == "locking":
            tpos = world.get_component(self.target, "Position")
            if tpos:
                tile = level.tile_at(tpos.x, tpos.y)
                if tile and tile.feature in ("door_closed",
                                             "door_open"):
                    tile.feature = "door_locked"
                    events.append(MessageEvent(
                        text=t("item.wand_lock_door"),
                    ))
                else:
                    events.append(MessageEvent(
                        text=t("item.wand_no_door"),
                    ))

        elif effect == "digging":
            tpos = world.get_component(self.target, "Position")
            if tpos:
                tile = level.tile_at(tpos.x, tpos.y)
                if tile and tile.terrain == Terrain.WALL:
                    tile.terrain = Terrain.FLOOR
                    events.append(MessageEvent(
                        text=t("item.dig_cast"),
                    ))
                else:
                    events.append(MessageEvent(
                        text=t("item.dig_no_wall"),
                    ))

        real_id = world.get_component(self.item, "_potion_id") or ""
        events.append(ItemUsed(
            entity=self.actor, item=self.item, effect=f"wand_{effect}",
            item_id=real_id,
        ))

        return events
