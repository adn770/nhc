"""Sub-hex movement action within a hex flower.

Moves the player one sub-hex inside the flower, advancing the
clock by the destination's ``move_cost_hours``, updating the
exploration sub-hex position, and revealing the ring-1 FOV.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.events import Event, HexStepEvent
from nhc.hexcrawl.coords import HexCoord, distance
from nhc.hexcrawl.model import FLOWER_COORDS

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.model import HexWorld


class MoveSubHexAction(Action):
    """Step the player one sub-hex within a hex flower."""

    def __init__(
        self,
        actor: int,
        origin: HexCoord,
        target: HexCoord,
        hex_world: "HexWorld",
    ) -> None:
        super().__init__(actor)
        self.origin = origin
        self.target = target
        self.hex_world = hex_world

    def validate_sync(self) -> bool:
        """Synchronous validation for use in tests and game loop."""
        if self.target not in FLOWER_COORDS:
            return False
        if distance(self.origin, self.target) != 1:
            return False
        return True

    async def validate(
        self, world: "World", level: "Level | None" = None,
    ) -> bool:
        return self.validate_sync()

    def execute_sync(self) -> list[Event]:
        """Synchronous execution for use in tests and game loop."""
        macro = self.hex_world.exploring_hex
        assert macro is not None
        cell = self.hex_world.get_cell(macro)
        assert cell is not None and cell.flower is not None
        sub_cell = cell.flower.cells.get(self.target)
        assert sub_cell is not None
        self.hex_world.advance_clock_hours(sub_cell.move_cost_hours)
        self.hex_world.move_sub_hex(self.target)
        return [HexStepEvent(actor=self.actor, target=self.target)]

    async def execute(
        self, world: "World", level: "Level | None" = None,
    ) -> list[Event]:
        return self.execute_sync()
