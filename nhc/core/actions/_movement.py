"""Movement, stairs, and bump-resolution actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action, _crossing_door_edge
from nhc.core.actions._helpers import _announce_ground_items, _msg
from nhc.core.actions._traps import _check_traps
from nhc.core.events import DoorOpened, Event, MessageEvent
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


class MoveAction(Action):
    """Move in a direction."""

    def __init__(self, actor: int, dx: int, dy: int,
                 edge_doors: bool = False) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy
        self.edge_doors = edge_doors

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)
        if not tile:
            return False
        door_feats = ("door_closed", "door_locked", "door_secret")
        if tile.feature in door_feats:
            if self.edge_doors:
                return True  # edge mode: validate passes; execute decides
            elif tile.feature != "door_secret":
                return True  # center mode: bump opens (not secret)
        # Edge doors: check if leaving current tile crosses a door edge
        if self.edge_doors:
            cur = level.tile_at(pos.x, pos.y)
            if (cur and cur.feature in door_feats
                    and _crossing_door_edge(self.dx, self.dy, cur,
                                            entering=False)):
                return True
        return tile.walkable

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)

        if self.edge_doors:
            # -- Edge door mode (web): directional crossing --
            cur = level.tile_at(pos.x, pos.y)
            door_feats = ("door_closed", "door_locked", "door_secret")

            door_tile = None
            door_x, door_y = nx, ny
            # Entering a door tile from the door-side direction
            if tile.feature in door_feats:
                if _crossing_door_edge(self.dx, self.dy, tile,
                                       entering=True):
                    door_tile = tile
            # Leaving a door tile through the door edge
            if (not door_tile and cur
                    and cur.feature in door_feats
                    and _crossing_door_edge(self.dx, self.dy, cur,
                                            entering=False)):
                door_tile = cur
                door_x, door_y = pos.x, pos.y

            # Secret door blocks crossing (feels like a wall)
            if door_tile and door_tile.feature == "door_secret":
                events.append(MessageEvent(
                    text=_msg("explore.nothing_special", world,
                              actor=self.actor),
                ))
                return events

            if door_tile and door_tile.feature == "door_locked":
                events.append(MessageEvent(
                    text=_msg("explore.door_locked", world,
                              actor=self.actor),
                ))
                return events

            if door_tile and door_tile.feature == "door_closed":
                door_tile.feature = "door_open"
                events.append(DoorOpened(
                    entity=self.actor, x=door_x, y=door_y))
                events.append(MessageEvent(
                    text=_msg("explore.open_door", world,
                              actor=self.actor),
                ))
                return events

            # Not crossing door edge: just move onto the tile
            if tile.feature in door_feats:
                pos.x = nx
                pos.y = ny
                return events
        else:
            # -- Center door mode (terminal): bump to open --
            if tile.feature == "door_locked":
                events.append(MessageEvent(
                    text=_msg("explore.door_locked", world,
                              actor=self.actor),
                ))
                return events

            if tile.feature == "door_closed":
                tile.feature = "door_open"
                events.append(DoorOpened(
                    entity=self.actor, x=nx, y=ny))
                events.append(MessageEvent(
                    text=_msg("explore.open_door", world,
                              actor=self.actor),
                ))
                return events

        # Auto-open chests when bumping into them
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                if world.has_component(eid, "Chest"):
                    from nhc.core.actions._interaction import OpenChestAction
                    chest_action = OpenChestAction(
                        actor=self.actor, chest=eid,
                    )
                    if await chest_action.validate(world, level):
                        return await chest_action.execute(world, level)
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


class AscendStairsAction(Action):
    """Ascend to the previous dungeon level."""

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x, pos.y)
        return tile is not None and tile.feature == "stairs_up"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.core.events import LevelEntered
        if level.depth <= 1:
            return [MessageEvent(
                text=t("explore.surface_blocked"),
            )]
        return [
            LevelEntered(
                entity=self.actor,
                level_id=level.id,
                depth=level.depth - 1,
            ),
            MessageEvent(text=t("explore.ascend")),
        ]


class BumpAction(Action):
    """Smart directional action: attack, open door, or move."""

    def __init__(self, actor: int, dx: int, dy: int,
                 edge_doors: bool = False) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy
        self.edge_doors = edge_doors

    def resolve(self, world: "World", level: "Level") -> Action | None:
        """Convert bump into a concrete action."""
        from nhc.core.actions._combat import MeleeAttackAction
        from nhc.core.actions._interaction import OpenChestAction

        pos = world.get_component(self.actor, "Position")
        if not pos:
            return None
        nx, ny = pos.x + self.dx, pos.y + self.dy

        # Check for blocking entities at target
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                # Chests: open instead of attack
                if world.has_component(eid, "Chest"):
                    return OpenChestAction(actor=self.actor, chest=eid)
                # Creatures: attack
                return MeleeAttackAction(actor=self.actor, target=eid)

        # Otherwise: move (handles doors internally)
        return MoveAction(actor=self.actor, dx=self.dx, dy=self.dy,
                          edge_doors=self.edge_doors)

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        resolved = self.resolve(world, level)
        if resolved is None:
            return []
        if await resolved.validate(world, level):
            return await resolved.execute(world, level)
        return []
