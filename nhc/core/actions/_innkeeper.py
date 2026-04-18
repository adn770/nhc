"""InnkeeperInteractAction — overland rumor exchange."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.events import Event, MessageEvent
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.model import HexWorld

logger = logging.getLogger(__name__)


class InnkeeperInteractAction(Action):
    """Bump an innkeeper and hear a rumor from the overland pool.

    Consumes the head of :attr:`HexWorld.active_rumors` via
    :func:`nhc.hexcrawl.rumors.gather_rumor_at`, applies the
    reveal side-effect, and emits a localized
    :class:`MessageEvent` so the player sees the lead. An empty
    pool yields a polite "nothing new today" beat so the bump
    still gets feedback.
    """

    def __init__(
        self,
        actor: int,
        innkeeper_id: int,
        hex_world: "HexWorld | None" = None,
    ) -> None:
        super().__init__(actor)
        self.innkeeper_id = innkeeper_id
        self.hex_world = hex_world

    async def validate(self, world: "World", level: "Level") -> bool:
        if not world.has_component(self.innkeeper_id, "RumorVendor"):
            return False
        apos = world.get_component(self.actor, "Position")
        ipos = world.get_component(self.innkeeper_id, "Position")
        if apos is None or ipos is None:
            return False
        return (
            abs(apos.x - ipos.x) <= 1 and abs(apos.y - ipos.y) <= 1
        )

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.hexcrawl.rumor_pool import consume_rumor

        if self.hex_world is None:
            # No overland context -- nothing to dispense. Quietly
            # fail open rather than 500 if the action is triggered
            # in a dungeon-mode game somehow.
            return [MessageEvent(text=t("rumor.none"))]
        rumor = consume_rumor(self.hex_world)
        if rumor is None:
            # Pool is empty. If the player has heard rumors here
            # before (last_rumor_day > 0) the innkeeper already
            # gave up everything they knew and is politely asking
            # for patience until fresh news arrives. Otherwise
            # they simply haven't heard anything yet.
            if self.hex_world.last_rumor_day > 0:
                return [MessageEvent(text=t("rumor.come_back_later"))]
            return [MessageEvent(text=t("rumor.none"))]
        if rumor.reveals is None:
            return [MessageEvent(text=rumor.text)]
        logger.info(
            "Innkeeper shared rumor %s (truth=%s, reveals=(%d, %d))",
            rumor.id, rumor.truth, rumor.reveals.q, rumor.reveals.r,
        )
        return [MessageEvent(text=rumor.text)]
