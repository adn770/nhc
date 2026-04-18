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
    :func:`nhc.hexcrawl.rumor_pool.consume_rumor`, applies the
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
            return [MessageEvent(text=t("rumor.none"))]
        rumor = consume_rumor(self.hex_world)
        if rumor is None:
            events: list[Event] = []
            if self.hex_world.last_rumor_day > 0:
                events.append(
                    MessageEvent(text=t("rumor.come_back_later")),
                )
            else:
                events.append(MessageEvent(text=t("rumor.none")))
            chatter = self._roll_chatter()
            if chatter:
                events.append(MessageEvent(text=chatter))
            return events
        if rumor.reveals is None:
            return [MessageEvent(text=rumor.text)]
        logger.info(
            "Innkeeper shared rumor %s (truth=%s, reveals=(%d, %d))",
            rumor.id, rumor.truth, rumor.reveals.q, rumor.reveals.r,
        )
        return [MessageEvent(text=rumor.text)]

    def _roll_chatter(self) -> str | None:
        """Roll an ephemeral chatter line from the innkeeper."""
        try:
            from nhc.i18n import current_lang
            from nhc.tables import roll_ephemeral

            result = roll_ephemeral(
                "innkeeper.chatter", lang=current_lang(),
            )
            return result.text
        except Exception:
            return None
