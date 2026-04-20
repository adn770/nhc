"""Movement, stairs, and bump-resolution actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action, _crossing_door_edge
from nhc.core.actions._helpers import _announce_ground_items, _msg
from nhc.core.actions._traps import _check_traps
from nhc.core.events import (
    DoorOpened,
    Event,
    LeaveSiteRequested,
    MessageEvent,
)
from nhc.i18n import t
from nhc.utils.spatial import chebyshev

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


# Behaviors counted as "hostile" for the purpose of player
# retreat narration. Idle creatures (merchants, mold) and the
# player's own henchmen are excluded.
_HOSTILE_RETREAT_BEHAVIORS = frozenset({
    "aggressive_melee", "guard", "shrieker",
})


def _min_visible_hostile_distance(
    world: "World", level: "Level", x: int, y: int,
) -> int | None:
    """Return the minimum Chebyshev distance from ``(x, y)`` to
    any hostile creature whose current tile is visible to the
    player. Returns ``None`` when no visible hostile is on the
    map — the caller should treat that as "no retreat to
    narrate"."""
    best: int | None = None
    for eid, ai, epos in world.query("AI", "Position"):
        if ai.behavior not in _HOSTILE_RETREAT_BEHAVIORS:
            continue
        tile = level.tile_at(epos.x, epos.y)
        if not tile or not tile.visible:
            continue
        d = chebyshev(x, y, epos.x, epos.y)
        if best is None or d < best:
            best = d
    return best


def _can_open_doors(world: "World", actor: int) -> bool:
    """Players and humanoid creatures can open doors."""
    if world.has_component(actor, "Player"):
        return True
    ai = world.get_component(actor, "AI")
    if not ai:
        return False
    from nhc.ai.behavior import HUMANOID_FACTIONS
    return ai.faction in HUMANOID_FACTIONS


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
        if not tile.walkable:
            return False

        # Henchmen must not walk onto the player or other henchmen
        if world.has_component(self.actor, "Henchman"):
            for eid, epos in world.query("Position"):
                if eid == self.actor or epos.x != nx or epos.y != ny:
                    continue
                if world.has_component(eid, "Player"):
                    return False
                h = world.get_component(eid, "Henchman")
                if h and h.hired:
                    return False

        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)

        # Snapshot pre-move distance for the player retreat cue.
        # Only the player gets the "you back away" narration, and
        # only when a visible hostile actually exists.
        pre_retreat_dist: int | None = None
        if world.has_component(self.actor, "Player"):
            pre_retreat_dist = _min_visible_hostile_distance(
                world, level, pos.x, pos.y,
            )

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
                if not _can_open_doors(world, self.actor):
                    return events  # non-humanoid blocked silently
                events.append(MessageEvent(
                    text=_msg("explore.door_locked", world,
                              actor=self.actor),
                ))
                return events

            if door_tile and door_tile.feature == "door_closed":
                if not _can_open_doors(world, self.actor):
                    return events  # non-humanoid blocked silently
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
                if not _can_open_doors(world, self.actor):
                    return events  # non-humanoid blocked silently
                events.append(MessageEvent(
                    text=_msg("explore.door_locked", world,
                              actor=self.actor),
                ))
                return events

            if tile.feature == "door_closed":
                if not _can_open_doors(world, self.actor):
                    return events  # non-humanoid blocked silently
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

        # Player retreat cue: if the step strictly increased the
        # minimum distance to any visible hostile, narrate that
        # the hero is backing away. Gives the player a tactile
        # signal that disengagement is working.
        if pre_retreat_dist is not None:
            post_retreat_dist = _min_visible_hostile_distance(
                world, level, nx, ny,
            )
            if (post_retreat_dist is not None
                    and post_retreat_dist > pre_retreat_dist):
                events.append(MessageEvent(
                    text=t("explore.retreat"),
                ))

        return events


def _building_upper_floor(level: "Level") -> bool:
    """True when ``level`` is an upper floor of a building (not
    the ground floor and not a dungeon). Used by the stair
    actions to flip depth direction: inside a building, physical
    up corresponds to a *higher* floor_index and therefore a
    higher cache depth, while physical down is a lower depth."""
    return (
        getattr(level, "building_id", None) is not None
        and (level.floor_index or 0) > 0
    )


def _building_floor(level: "Level") -> bool:
    return getattr(level, "building_id", None) is not None


class DescendStairsAction(Action):
    """Descend one step.

    * Dungeon floor: depth + 1 (deeper).
    * Building upper floor: depth - 1 (physically down = lower
      floor index).
    * Building ground floor with a descent stair (the only
      ``stairs_down`` on that level): depth + 1, routed by the
      game loop to the dungeon descent pipeline.
    """

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x, pos.y)
        return tile is not None and tile.feature == "stairs_down"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.core.events import LevelEntered
        if _building_upper_floor(level):
            target = level.depth - 1
        else:
            target = level.depth + 1
        return [
            LevelEntered(
                entity=self.actor,
                level_id=level.id,
                depth=target,
            ),
            MessageEvent(text=t("explore.descend")),
        ]


class AscendStairsAction(Action):
    """Ascend one step.

    * Dungeon floor: depth - 1 (shallower).
    * Any building floor with a ``stairs_up``: depth + 1. In a
      building ``floor_index + 1`` is physically *above*, so the
      cache slot for the next floor up lives at ``depth + 1``.
    """

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x, pos.y)
        return tile is not None and tile.feature == "stairs_up"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.core.events import LevelEntered
        if _building_floor(level):
            target = level.depth + 1
        else:
            if level.depth <= 1:
                return [MessageEvent(
                    text=t("explore.surface_blocked"),
                )]
            target = level.depth - 1
        return [
            LevelEntered(
                entity=self.actor,
                level_id=level.id,
                depth=target,
            ),
            MessageEvent(text=t("explore.ascend")),
        ]


class SwapAction(Action):
    """Swap positions with a hired henchman."""

    def __init__(self, actor: int, target: int,
                 dx: int, dy: int) -> None:
        super().__init__(actor)
        self.target = target
        self.dx = dx
        self.dy = dy

    async def validate(self, world: "World", level: "Level") -> bool:
        hench = world.get_component(self.target, "Henchman")
        if not hench or not hench.hired:
            return False
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        apos = world.get_component(self.actor, "Position")
        tpos = world.get_component(self.target, "Position")
        if not apos or not tpos:
            return []
        # Swap coordinates
        apos.x, apos.y, tpos.x, tpos.y = tpos.x, tpos.y, apos.x, apos.y
        # Check traps at new player position
        events = _check_traps(
            world, level, self.actor, apos.x, apos.y,
        )
        events += _announce_ground_items(
            world, apos.x, apos.y, self.actor,
        )
        return events


class LeaveSiteAction(Action):
    """Step off the edge of a Site surface back to the overland.

    Emitted when the player bumps the boundary of a walled-site
    (keep, town, farm, ...) surface Level from the outside of
    any in-bounds tile. The action emits :class:`LeaveSiteRequested`
    and a narration :class:`MessageEvent`; the :class:`Game`
    handler drops the level and restores the flower view.
    """

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        # The destination tile is off-map by construction; the
        # bump router is the authority for when this action is
        # chosen so we just sanity-check the step lands outside.
        nx, ny = pos.x + self.dx, pos.y + self.dy
        return level.tile_at(nx, ny) is None

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return [
            LeaveSiteRequested(actor=self.actor),
            MessageEvent(text=t("leave_site.exit")),
        ]


class BumpAction(Action):
    """Smart directional action: attack, open door, or move."""

    def __init__(
        self,
        actor: int,
        dx: int,
        dy: int,
        edge_doors: bool = False,
        hex_world: "object | None" = None,
    ) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy
        self.edge_doors = edge_doors
        # Threaded through to InnkeeperInteractAction when the
        # bump lands on a RumorVendor. None for dungeon-mode
        # games -- InnkeeperInteractAction.execute degrades
        # gracefully.
        self.hex_world = hex_world

    def resolve(self, world: "World", level: "Level") -> Action | None:
        """Convert bump into a concrete action."""
        from nhc.core.actions._base import _closed_door_blocks
        from nhc.core.actions._combat import MeleeAttackAction
        from nhc.core.actions._interaction import OpenChestAction

        pos = world.get_component(self.actor, "Position")
        if not pos:
            return None
        nx, ny = pos.x + self.dx, pos.y + self.dy

        # A closed edge-door between the actor and the target
        # tile makes attacks and chest-opens impossible. Skip
        # the blocking-entity scan entirely in that case and
        # fall through to MoveAction, which opens the door as
        # its side effect — otherwise a creature parked on the
        # far side of the door hijacks the bump into a melee
        # that can never land and stalls the player.
        door_blocks = _closed_door_blocks(
            level, pos.x, pos.y, nx, ny)

        if not door_blocks:
            for eid, _, bpos in world.query(
                "BlocksMovement", "Position",
            ):
                if (bpos.x == nx and bpos.y == ny
                        and eid != self.actor):
                    # Chests: open instead of attack
                    if world.has_component(eid, "Chest"):
                        return OpenChestAction(
                            actor=self.actor, chest=eid)
                    # Priests: open temple menu instead of attack
                    if world.has_component(eid, "TempleServices"):
                        from nhc.core.actions._temple import (
                            TempleInteractAction,
                        )
                        return TempleInteractAction(
                            actor=self.actor, priest=eid)
                    # Merchants: open shop instead of attack
                    if world.has_component(eid, "ShopInventory"):
                        from nhc.core.actions._shop import (
                            ShopInteractAction,
                        )
                        return ShopInteractAction(
                            actor=self.actor, merchant=eid)
                    # Unhired adventurers: open encounter menu
                    hench = world.get_component(eid, "Henchman")
                    if hench and not hench.hired:
                        from nhc.core.actions._henchman import (
                            HenchmanInteractAction,
                        )
                        return HenchmanInteractAction(
                            actor=self.actor, henchman_id=eid)
                    # Innkeepers: dispense a rumor. The overland
                    # HexWorld isn't reachable from BumpAction so
                    # the caller (game loop) fills it in before
                    # execute().
                    if world.has_component(eid, "RumorVendor"):
                        from nhc.core.actions._innkeeper import (
                            InnkeeperInteractAction,
                        )
                        return InnkeeperInteractAction(
                            actor=self.actor, innkeeper_id=eid,
                            hex_world=self.hex_world,
                        )
                    # Rumour signs: read the next active rumour.
                    if world.has_component(eid, "RumorSign"):
                        from nhc.core.actions._sign import (
                            SignReadAction,
                        )
                        return SignReadAction(
                            actor=self.actor, sign_id=eid,
                            hex_world=self.hex_world,
                        )
                    # Creatures: attack
                    return MeleeAttackAction(
                        actor=self.actor, target=eid)

        # Hired henchmen: swap positions instead of blocking
        if world.has_component(self.actor, "Player"):
            for eid, epos in world.query("Position"):
                if eid == self.actor:
                    continue
                if epos.x != nx or epos.y != ny:
                    continue
                hench = world.get_component(eid, "Henchman")
                if hench and hench.hired and hench.owner == self.actor:
                    return SwapAction(
                        actor=self.actor, target=eid,
                        dx=self.dx, dy=self.dy,
                    )

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
