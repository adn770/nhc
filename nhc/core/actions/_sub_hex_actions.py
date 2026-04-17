"""Sub-hex exploration actions: search, forage, rest, interact.

Each action advances the clock by its turn cost and produces
effects appropriate to the current sub-hex's biome and features.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.events import Event, MessageEvent

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.model import HexWorld


class SearchSubHexAction(Action):
    """Search the current sub-hex for hidden features or loot.

    Takes 10-20 minutes. Fails if already searched.
    """

    def __init__(
        self,
        actor: int,
        hex_world: "HexWorld",
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(actor)
        self.hex_world = hex_world
        self.rng = rng or random.Random()

    def validate_sync(self) -> bool:
        macro = self.hex_world.exploring_hex
        sub = self.hex_world.exploring_sub_hex
        if macro is None or sub is None:
            return False
        cell = self.hex_world.get_cell(macro)
        if cell is None or cell.flower is None:
            return False
        sc = cell.flower.cells.get(sub)
        if sc is None:
            return False
        return not sc.searched

    async def validate(
        self, world: "World", level: "Level | None" = None,
    ) -> bool:
        return self.validate_sync()

    def execute_sync(self) -> list[Event]:
        macro = self.hex_world.exploring_hex
        sub = self.hex_world.exploring_sub_hex
        cell = self.hex_world.get_cell(macro)
        sc = cell.flower.cells[sub]
        sc.searched = True
        # 10-20 minutes
        minutes = self.rng.randint(10, 20)
        self.hex_world.advance_clock_hours(minutes / 60)
        msg = "You search the area."
        if sc.minor_feature.value != "none":
            msg = f"You find a {sc.minor_feature.value.replace('_', ' ')}."
        return [MessageEvent(text=msg)]

    async def execute(
        self, world: "World", level: "Level | None" = None,
    ) -> list[Event]:
        return self.execute_sync()


class ForageSubHexAction(Action):
    """Forage for herbs, food, or materials.

    Takes 10-20 minutes. Always valid while in a flower.
    """

    def __init__(
        self,
        actor: int,
        hex_world: "HexWorld",
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(actor)
        self.hex_world = hex_world
        self.rng = rng or random.Random()

    def validate_sync(self) -> bool:
        return (
            self.hex_world.exploring_hex is not None
            and self.hex_world.exploring_sub_hex is not None
        )

    async def validate(
        self, world: "World", level: "Level | None" = None,
    ) -> bool:
        return self.validate_sync()

    def execute_sync(self) -> list[Event]:
        macro = self.hex_world.exploring_hex
        sub = self.hex_world.exploring_sub_hex
        cell = self.hex_world.get_cell(macro)
        sc = cell.flower.cells[sub]
        minutes = self.rng.randint(10, 20)
        self.hex_world.advance_clock_hours(minutes / 60)
        # Biome determines yield
        good_biomes = {"forest", "greenlands", "hills", "marsh"}
        if sc.biome.value in good_biomes:
            msg = "You find some useful herbs and berries."
        else:
            msg = "Slim pickings here."
        return [MessageEvent(text=msg)]

    async def execute(
        self, world: "World", level: "Level | None" = None,
    ) -> list[Event]:
        return self.execute_sync()


class RestSubHexAction(Action):
    """Rest to recover HP.

    Takes 30 minutes (3 ten-minute turns). Heals 1-3 HP.
    """

    def __init__(
        self,
        actor: int,
        hex_world: "HexWorld",
        ecs_world: "World | None" = None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(actor)
        self.hex_world = hex_world
        self.ecs_world = ecs_world
        self.rng = rng or random.Random()

    def validate_sync(self) -> bool:
        return (
            self.hex_world.exploring_hex is not None
            and self.hex_world.exploring_sub_hex is not None
        )

    async def validate(
        self, world: "World", level: "Level | None" = None,
    ) -> bool:
        return self.validate_sync()

    def execute_sync(self) -> list[Event]:
        self.hex_world.advance_clock_hours(0.5)  # 30 minutes
        heal = self.rng.randint(1, 3)
        if self.ecs_world is not None:
            health = self.ecs_world.get_component(
                self.actor, "Health",
            )
            if health is not None:
                health.current = min(
                    health.maximum, health.current + heal,
                )
        return [MessageEvent(text=f"You rest and recover {heal} HP.")]

    async def execute(
        self, world: "World", level: "Level | None" = None,
    ) -> list[Event]:
        return self.execute_sync()
