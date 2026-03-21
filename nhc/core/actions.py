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
    LootTable,
    Position,
    Renderable,
    Stats,
    Trap,
    Weapon,
)
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
            actor_desc = _entity_name(world, self.actor)
            events.append(MessageEvent(
                text=f"{actor_desc} opens a door.",
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
                                text=f"{target_name} drops: "
                                     f"{', '.join(names)}.",
                            ))

                # Leave a corpse marker, then destroy
                if tpos:
                    corpse_name = f"{target_name} corpse"
                    world.create_entity({
                        "Position": Position(
                            x=tpos.x, y=tpos.y, level_id=tpos.level_id,
                        ),
                        "Renderable": Renderable(
                            glyph="%", color="bright_red", render_order=0,
                        ),
                        "Description": Description(name=corpse_name),
                    })

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
        self.full = False

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv:
            return False
        if len(inv.slots) >= inv.max_slots:
            self.full = True
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
                if health.current >= health.maximum:
                    events.append(MessageEvent(
                        text=f"Already at full health.",
                    ))
                    return events
                amount = roll_dice(consumable.dice)
                actual = heal(health, amount)
                events.append(ItemUsed(
                    entity=self.actor, item=self.item, effect="heal",
                ))
                events.append(MessageEvent(
                    text=f"Quaff {item_name}. Healed {actual} HP.",
                ))

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
            feature_names = {
                "stairs_up": "stairs leading up",
                "stairs_down": "stairs leading down",
                "door_open": "an open door",
                "door_closed": "a closed door",
            }
            fname = feature_names.get(tile.feature, tile.feature)
            events.append(MessageEvent(text=f"You see {fname} here."))

        # Describe items on tile
        items = _items_at(world, pos.x, pos.y, self.actor)
        for eid in items:
            desc = world.get_component(eid, "Description")
            if desc and desc.long:
                events.append(MessageEvent(text=desc.long))
            elif desc:
                events.append(MessageEvent(text=f"You see {desc.short}."))

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
                            hp_desc = " (uninjured)"
                        elif pct > 0.5:
                            hp_desc = " (lightly wounded)"
                        elif pct > 0.25:
                            hp_desc = " (badly wounded)"
                        else:
                            hp_desc = " (near death)"
                    events.append(MessageEvent(
                        text=f"You see {desc.short}{hp_desc}.",
                    ))

        if not events:
            events.append(MessageEvent(text="Nothing special here."))

        return events


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
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        resolved = self.resolve(world, level)
        if await resolved.validate(world, level):
            return await resolved.execute(world, level)
        return []


# ── Helpers ──────────────────────────────────────────────────────────


def _entity_name(world: "World", eid: int) -> str:
    """Get display name for an entity."""
    desc = world.get_component(eid, "Description")
    if desc and desc.name:
        return desc.name
    player = world.get_component(eid, "Player")
    if player is not None:
        return "You"
    return "something"


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
        name = desc.short if desc else "something"
        events.append(MessageEvent(text=f"You see {name} here."))
    else:
        names = []
        for eid in items:
            desc = world.get_component(eid, "Description")
            names.append(desc.name if desc else "???")
        events.append(MessageEvent(
            text=f"You see {len(items)} items here: {', '.join(names)}.",
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
