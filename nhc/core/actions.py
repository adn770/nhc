"""Action resolution pipeline."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

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
    BlocksMovement,
    Consumable,
    Description,
    Equipment,
    Health,
    Inventory,
    Position,
    Stats,
    Trap,
    Weapon,
)
from nhc.rules.combat import apply_damage, heal, is_dead, resolve_melee_attack
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
        # Closed doors can be bumped open
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
            actor_desc = _entity_name(world, self.actor)
            events.append(MessageEvent(
                text=f"{actor_desc} opens a door.",
            ))
            # Opening a door costs the move — don't step into the tile
            return events

        # Check for blocking creatures at target
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                return []  # Blocked

        # Move
        pos.x = nx
        pos.y = ny

        # Check for traps
        events += _check_traps(world, level, self.actor, nx, ny)

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

        # Get weapon damage
        weapon_damage = "1d4"  # Unarmed
        equip = world.get_component(self.actor, "Equipment")
        if equip and equip.weapon is not None:
            wpn = world.get_component(equip.weapon, "Weapon")
            if wpn:
                weapon_damage = wpn.damage

        hit, damage = resolve_melee_attack(a_stats, t_stats, weapon_damage)

        attacker_name = _entity_name(world, self.actor)
        target_name = _entity_name(world, self.target)

        if hit:
            actual = apply_damage(t_health, damage)
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=actual, hit=True,
            ))
            events.append(MessageEvent(
                text=f"{attacker_name} hits {target_name} for {actual} damage.",
            ))

            if is_dead(t_health):
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                ))
                events.append(MessageEvent(
                    text=f"{target_name} is slain!",
                ))
                # Remove dead creature from world
                world.destroy_entity(self.target)
        else:
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=0, hit=False,
            ))
            events.append(MessageEvent(
                text=f"{attacker_name} misses {target_name}.",
            ))

        return events


class PickupItemAction(Action):
    """Pick up an item from the ground."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv:
            return False
        if len(inv.slots) >= inv.max_slots:
            return False
        item_pos = world.get_component(self.item, "Position")
        actor_pos = world.get_component(self.actor, "Position")
        if not item_pos or not actor_pos:
            return False
        return item_pos.x == actor_pos.x and item_pos.y == actor_pos.y

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")

        inv.slots.append(self.item)
        # Remove position so it's no longer on the map
        world.add_component(self.item, "Position", None)

        item_name = _entity_name(world, self.item)
        events.append(ItemPickedUp(entity=self.actor, item=self.item))
        events.append(MessageEvent(
            text=f"Picked up {item_name}.",
        ))

        # Auto-equip weapon if nothing equipped
        wpn = world.get_component(self.item, "Weapon")
        equip = world.get_component(self.actor, "Equipment")
        if wpn and equip and equip.weapon is None:
            equip.weapon = self.item
            events.append(MessageEvent(
                text=f"Equipped {item_name}.",
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
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")
        consumable = world.get_component(self.item, "Consumable")
        item_name = _entity_name(world, self.item)

        if consumable.effect == "heal":
            health = world.get_component(self.actor, "Health")
            if health:
                amount = roll_dice(consumable.dice)
                actual = heal(health, amount)
                events.append(ItemUsed(
                    entity=self.actor, item=self.item, effect="heal",
                ))
                events.append(MessageEvent(
                    text=f"Used {item_name}. Healed {actual} HP.",
                ))

        # Remove item from inventory and world
        if self.item in inv.slots:
            inv.slots.remove(self.item)
        world.destroy_entity(self.item)

        return events


class DescendStairsAction(Action):
    """Descend stairs (win condition for test level)."""

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x, pos.y)
        return tile is not None and tile.feature == "stairs_down"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return [
            GameWon(message="You descend deeper into the dungeon..."),
            MessageEvent(text="You descend the stairs. Victory!"),
        ]


class BumpAction(Action):
    """Smart directional action: attack, open door, or move."""

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    def resolve(self, world: "World", level: "Level") -> Action:
        """Convert bump into a concrete action."""
        pos = world.get_component(self.actor, "Position")
        nx, ny = pos.x + self.dx, pos.y + self.dy

        # Check for creature at target: attack
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                return MeleeAttackAction(actor=self.actor, target=eid)

        # Otherwise: move (handles doors internally)
        return MoveAction(actor=self.actor, dx=self.dx, dy=self.dy)

    async def validate(self, world: "World", level: "Level") -> bool:
        return True  # Resolved action will validate itself

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        resolved = self.resolve(world, level)
        if await resolved.validate(world, level):
            return await resolved.execute(world, level)
        return []


def _entity_name(world: "World", eid: int) -> str:
    """Get display name for an entity."""
    desc = world.get_component(eid, "Description")
    if desc and desc.name:
        return desc.name
    player = world.get_component(eid, "Player")
    if player is not None:
        return "You"
    return "something"


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
        dex_defense = 10 + (stats.dexterity if stats else 0)
        save_roll = d20()

        entity_name = _entity_name(world, entity_id)
        trap_desc = world.get_component(eid, "Description")
        trap_name = trap_desc.name if trap_desc else "a trap"

        if save_roll + (stats.dexterity if stats else 0) >= trap.dc:
            events.append(MessageEvent(
                text=f"{entity_name} notices {trap_name} and avoids it!",
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
                    text=f"{entity_name} falls into {trap_name}! "
                         f"{actual} damage!",
                ))

        trap.triggered = True
        trap.hidden = False

    return events
