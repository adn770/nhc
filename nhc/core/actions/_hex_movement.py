"""Overland hex movement action.

The action's job is small and well-scoped: step one hex, reveal
the destination's visible ring, mark it visited, advance the day
clock by the destination's biome cost, and emit a
:class:`HexStepEvent`. Dungeon-mode plumbing (``world``/``level``)
is accepted but not used -- hex moves never touch the ECS or any
dungeon :class:`Level`. Feature / settlement entry is a separate
action (M-1.12 / M-2.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.events import Event, HexStepEvent
from nhc.hexcrawl.coords import HexCoord, distance, in_bounds

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.model import HexWorld


class MoveHexAction(Action):
    """Step the player one hex on the overland map."""

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

    async def validate(
        self, world: "World", level: "Level | None" = None,
    ) -> bool:
        if not in_bounds(
            self.target, self.hex_world.width, self.hex_world.height,
        ):
            return False
        if distance(self.origin, self.target) != 1:
            return False
        # Destination cell must exist on the world (generator fills
        # the whole map, so this is belt-and-braces).
        if self.hex_world.get_cell(self.target) is None:
            return False
        return True

    async def execute(
        self, world: "World", level: "Level | None" = None,
    ) -> list[Event]:
        cell = self.hex_world.get_cell(self.target)
        assert cell is not None, "validate() should have rejected"
        self.hex_world.visit(self.target)
        self.hex_world.reveal_with_neighbors(self.target)
        self.hex_world.advance_clock_for_cell(cell)
        return [HexStepEvent(actor=self.actor, target=self.target)]
