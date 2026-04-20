"""Shared base for NPCs that dispense overland rumours.

Innkeepers, farmers, campsite travellers, and orchardists all
draw from :attr:`HexWorld.active_rumors` and narrate one line
per bump. Factoring the draw-and-narrate flow into
:class:`RumorVendorInteractAction` keeps the per-NPC subclasses
thin — :class:`InnkeeperInteractAction` layers inn-specific
chatter on top while the other three NPCs get the base behaviour
for free.
"""

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


class RumorVendorInteractAction(Action):
    """Bump a RumorVendor NPC and hear the next overland rumour.

    Subclasses can override :meth:`_on_empty_pool` to add
    NPC-flavored chatter on top of the fallback beat, and
    :meth:`_after_rumor` to tack on a bespoke reaction to the
    rumour itself.
    """

    def __init__(
        self,
        actor: int,
        vendor_id: int,
        hex_world: "HexWorld | None" = None,
    ) -> None:
        super().__init__(actor)
        self.vendor_id = vendor_id
        self.hex_world = hex_world

    async def validate(self, world: "World", level: "Level") -> bool:
        if not world.has_component(self.vendor_id, "RumorVendor"):
            return False
        apos = world.get_component(self.actor, "Position")
        vpos = world.get_component(self.vendor_id, "Position")
        if apos is None or vpos is None:
            return False
        return (
            abs(apos.x - vpos.x) <= 1 and abs(apos.y - vpos.y) <= 1
        )

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.hexcrawl.rumor_pool import consume_rumor

        if self.hex_world is None:
            return [MessageEvent(text=t("rumor.none"))]
        rumor = consume_rumor(self.hex_world)
        if rumor is None:
            return self._on_empty_pool()
        logger.info(
            "Rumor vendor shared %s (truth=%s)",
            rumor.id, rumor.truth,
        )
        events: list[Event] = [MessageEvent(text=rumor.text)]
        events.extend(self._after_rumor(rumor))
        return events

    # -- Subclass hooks -------------------------------------------------

    def _on_empty_pool(self) -> list[Event]:
        """Empty-pool fallback; subclasses override for NPC flavor."""
        if self.hex_world and self.hex_world.last_rumor_day > 0:
            return [MessageEvent(text=t("rumor.come_back_later"))]
        return [MessageEvent(text=t("rumor.none"))]

    def _after_rumor(self, rumor) -> list[Event]:
        """Optional reaction tacked onto the dispensed rumour."""
        return []
