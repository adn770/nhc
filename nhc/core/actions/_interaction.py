"""Interaction actions: chests, locks, doors, look, search."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.actions._helpers import _entity_name, _items_at, _msg
from nhc.core.events import DoorOpened, Event, MessageEvent
from nhc.i18n import t
from nhc.rules.combat import apply_damage
from nhc.rules.loot import generate_loot
from nhc.utils.rng import d20, get_rng, roll_dice
from nhc.utils.spatial import adjacent

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


class OpenChestAction(Action):
    """Open an adjacent chest, dropping its loot on the ground."""

    def __init__(self, actor: int, chest: int) -> None:
        super().__init__(actor)
        self.chest = chest

    async def validate(self, world: "World", level: "Level") -> bool:
        if not world.has_component(self.chest, "Chest"):
            return False
        apos = world.get_component(self.actor, "Position")
        cpos = world.get_component(self.chest, "Position")
        if not apos or not cpos:
            return False
        return adjacent(apos.x, apos.y, cpos.x, cpos.y)

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        cpos = world.get_component(self.chest, "Position")
        loot = world.get_component(self.chest, "LootTable")

        # Drop loot
        dropped_names: list[str] = []
        if loot and cpos:
            dropped = generate_loot(
                world, loot, cpos.x, cpos.y, cpos.level_id,
            )
            for did in dropped:
                d = world.get_component(did, "Description")
                if d:
                    dropped_names.append(d.short or d.name)

        # Mark as opened: remove Chest tag, BlocksMovement, change glyph
        world.remove_component(self.chest, "Chest")
        world.remove_component(self.chest, "BlocksMovement")
        world.remove_component(self.chest, "LootTable")
        r = world.get_component(self.chest, "Renderable")
        if r:
            r.glyph = "_"
            r.color = "yellow"

        if dropped_names:
            events.append(MessageEvent(
                text=t("explore.chest_loot",
                       items=", ".join(dropped_names)),
            ))
        else:
            events.append(MessageEvent(
                text=t("explore.chest_empty"),
            ))

        return events


class PickLockAction(Action):
    """Pick a lock on an adjacent door using lockpicks.

    DEX save DC 14.  On failure, 30% chance lockpicks break.
    """

    LOCK_DC = 14

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x + self.dx, pos.y + self.dy)
        if not tile or tile.feature != "door_locked":
            return False
        # Requires lockpicks in inventory
        inv = world.get_component(self.actor, "Inventory")
        if not inv:
            return False
        return any(
            world.has_component(eid, "Lockpicks") for eid in inv.slots
        )

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        tx, ty = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(tx, ty)

        stats = world.get_component(self.actor, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        roll = d20()

        if roll + dex_bonus >= self.LOCK_DC:
            tile.feature = "door_closed"
            events.append(MessageEvent(
                text=_msg("explore.pick_lock_success", world,
                          actor=self.actor),
            ))
        else:
            events.append(MessageEvent(
                text=_msg("explore.pick_lock_fail", world,
                          actor=self.actor),
            ))
            # 30% chance lockpicks break
            if get_rng().random() < 0.3:
                inv = world.get_component(self.actor, "Inventory")
                for eid in list(inv.slots):
                    if world.has_component(eid, "Lockpicks"):
                        inv.slots.remove(eid)
                        world.destroy_entity(eid)
                        events.append(MessageEvent(
                            text=t("explore.lockpicks_break"),
                        ))
                        break

        return events


class ForceDoorAction(Action):
    """Force open a locked door with brute strength.

    Base STR save DC 15.  On failure, take 1d4 damage.
    Using a tool lowers the effective DC:
      - Crowbar (ForceTool): -5 DC, 10% break chance
      - Melee weapon: -3 DC, 20% break chance
    """

    FORCE_DC = 15
    CROWBAR_BONUS = 5
    WEAPON_BONUS = 3
    CROWBAR_BREAK = 0.10
    WEAPON_BREAK = 0.20

    def __init__(
        self, actor: int, dx: int, dy: int,
        tool: int | None = None,
    ) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy
        self.tool = tool  # entity ID of tool/weapon, or None

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x + self.dx, pos.y + self.dy)
        return tile is not None and tile.feature == "door_locked"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        tx, ty = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(tx, ty)

        stats = world.get_component(self.actor, "Stats")
        str_bonus = stats.strength if stats else 0
        roll = d20()

        # Tool bonus
        dc = self.FORCE_DC
        is_crowbar = False
        tool_name = ""
        if self.tool is not None:
            tool_desc = world.get_component(self.tool, "Description")
            tool_name = tool_desc.name if tool_desc else "tool"
            if world.has_component(self.tool, "ForceTool"):
                dc -= self.CROWBAR_BONUS
                is_crowbar = True
            elif world.has_component(self.tool, "Weapon"):
                dc -= self.WEAPON_BONUS

        if roll + str_bonus >= dc:
            tile.feature = "door_open"
            events.append(DoorOpened(entity=self.actor, x=tx, y=ty))
            if self.tool is not None:
                events.append(MessageEvent(
                    text=_msg("explore.force_door_tool_success", world,
                              actor=self.actor, tool=tool_name),
                ))
            else:
                events.append(MessageEvent(
                    text=_msg("explore.force_door_success", world,
                              actor=self.actor),
                ))
        else:
            damage = roll_dice("1d4")
            health = world.get_component(self.actor, "Health")
            if health:
                actual = apply_damage(health, damage)
                events.append(MessageEvent(
                    text=_msg("explore.force_door_fail", world,
                              actor=self.actor, damage=actual),
                ))

        # Tool breakage check (on both success and failure)
        if self.tool is not None:
            break_chance = (self.CROWBAR_BREAK if is_crowbar
                            else self.WEAPON_BREAK)
            if get_rng().random() < break_chance:
                inv = world.get_component(self.actor, "Inventory")
                if inv and self.tool in inv.slots:
                    inv.slots.remove(self.tool)
                # Unequip if equipped
                equip = world.get_component(self.actor, "Equipment")
                if equip and equip.weapon == self.tool:
                    equip.weapon = None
                world.destroy_entity(self.tool)
                events.append(MessageEvent(
                    text=t("explore.tool_break", tool=tool_name),
                ))

        return events


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
