"""Base action classes and door-blocking helpers."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from nhc.core.events import Event, MessageEvent

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level, Tile


def _crossing_door_edge(
    dx: int, dy: int, door_tile: "Tile", entering: bool = True,
) -> bool:
    """True if movement crosses the door's wall edge.

    door_side is the edge of the tile where the door sits.
    When entering the tile, movement crosses the edge only if it
    comes from the door_side direction. When leaving, it crosses
    if moving toward the door_side.

    - door_side="west": crossed when entering from west (dx=+1)
      or leaving toward west (dx=-1)
    - door_side="east": crossed when entering from east (dx=-1)
      or leaving toward east (dx=+1)
    - door_side="north": crossed when entering from north (dy=+1)
      or leaving toward north (dy=-1)
    - door_side="south": crossed when entering from south (dy=-1)
      or leaving toward south (dy=+1)
    """
    side = door_tile.door_side
    if not side:
        return True  # no side info, treat as always blocking
    if entering:
        # Entering from the door_side direction
        if side == "west" and dx > 0:
            return True
        if side == "east" and dx < 0:
            return True
        if side == "north" and dy > 0:
            return True
        if side == "south" and dy < 0:
            return True
        return False
    else:
        # Leaving toward the door_side direction
        if side == "west" and dx < 0:
            return True
        if side == "east" and dx > 0:
            return True
        if side == "north" and dy < 0:
            return True
        if side == "south" and dy > 0:
            return True
        return False


_BLOCKING_DOOR_FEATURES = frozenset({"door_closed", "door_locked", "door_secret"})


def _closed_door_blocks(
    level: "Level", ax: int, ay: int, tx: int, ty: int,
) -> bool:
    """True if a closed/locked door blocks melee between two positions."""
    dx = tx - ax
    dy = ty - ay

    # Check door on attacker's tile (leaving through its edge)
    a_tile = level.tile_at(ax, ay)
    if (a_tile and a_tile.feature in _BLOCKING_DOOR_FEATURES
            and _crossing_door_edge(dx, dy, a_tile, entering=False)):
        return True

    # Check door on target's tile (entering through its edge)
    t_tile = level.tile_at(tx, ty)
    if (t_tile and t_tile.feature in _BLOCKING_DOOR_FEATURES
            and _crossing_door_edge(dx, dy, t_tile, entering=True)):
        return True

    return False


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


class ImpossibleAction(Action):
    """The LLM determined the player's intent is not possible."""

    def __init__(self, actor: int, reason: str = "") -> None:
        super().__init__(actor)
        self.reason = reason

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return [MessageEvent(text=self.reason)]


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
        from nhc.utils.rng import d20

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
