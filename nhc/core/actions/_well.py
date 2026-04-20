"""Wayside well interaction: heal 1 HP and a 30% rumour roll."""

from __future__ import annotations

import random as _random
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.events import Event, MessageEvent
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.model import HexWorld


class WellInteractAction(Action):
    """Drink from a wayside well.

    Side-effects:

    * Heals ``+1`` HP up to :class:`Health.maximum`.
    * Rolls against ``rng.random() < RUMOUR_CHANCE`` and, on a
      hit, consumes the next overland rumour via
      :func:`consume_rumor` and surfaces its text.

    The rumour roll fires whether the heal landed or not — a
    full-HP drink still gives the well a chance to whisper. An
    empty pool collapses to a "water is cool" beat so the bump
    is always acknowledged.
    """

    RUMOUR_CHANCE = 0.3

    def __init__(
        self,
        actor: int,
        well_id: int,
        hex_world: "HexWorld | None" = None,
        rng: "_random.Random | object | None" = None,
    ) -> None:
        super().__init__(actor)
        self.well_id = well_id
        self.hex_world = hex_world
        self.rng = rng or _random.Random()

    async def validate(self, world: "World", level: "Level") -> bool:
        if not world.has_component(self.well_id, "WellDrink"):
            return False
        apos = world.get_component(self.actor, "Position")
        wpos = world.get_component(self.well_id, "Position")
        if apos is None or wpos is None:
            return False
        return (
            abs(apos.x - wpos.x) <= 1 and abs(apos.y - wpos.y) <= 1
        )

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.hexcrawl.rumor_pool import consume_rumor

        events: list[Event] = []
        health = world.get_component(self.actor, "Health")
        healed = False
        if health is not None and health.current < health.maximum:
            health.current = min(health.maximum, health.current + 1)
            healed = True
            events.append(MessageEvent(text=t("action.well_drink.healed")))

        surfaced = False
        if self.rng.random() < self.RUMOUR_CHANCE:
            rumor = (
                consume_rumor(self.hex_world)
                if self.hex_world is not None
                else None
            )
            if rumor is not None:
                events.append(MessageEvent(text=rumor.text))
                surfaced = True

        if not healed and not surfaced:
            events.append(MessageEvent(text=t("action.well_drink.rumour")))

        return events
