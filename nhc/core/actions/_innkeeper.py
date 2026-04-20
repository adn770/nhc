"""InnkeeperInteractAction — overland rumor exchange."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.core.actions._rumor_vendor import RumorVendorInteractAction
from nhc.core.events import Event, MessageEvent

if TYPE_CHECKING:
    from nhc.hexcrawl.model import HexWorld

logger = logging.getLogger(__name__)


class InnkeeperInteractAction(RumorVendorInteractAction):
    """Bump an innkeeper and hear a rumor from the overland pool.

    Inherits the generic rumour-draw flow from
    :class:`RumorVendorInteractAction` and layers in a tavern-
    chatter line on the empty-pool fallback so the innkeeper feels
    alive even when the pool has dried up.
    """

    def __init__(
        self,
        actor: int,
        innkeeper_id: int,
        hex_world: "HexWorld | None" = None,
    ) -> None:
        super().__init__(
            actor=actor, vendor_id=innkeeper_id,
            hex_world=hex_world,
        )
        # Preserve the historical attribute name; existing test
        # suites read ``.innkeeper_id`` off the action instance.
        self.innkeeper_id = innkeeper_id

    def _on_empty_pool(self) -> list[Event]:
        events = super()._on_empty_pool()
        chatter = self._roll_chatter()
        if chatter:
            events.append(MessageEvent(text=chatter))
        return events

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
