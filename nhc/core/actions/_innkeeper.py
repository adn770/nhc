"""InnkeeperInteractAction — thin back-compat shim.

Chatter rolling now lives on :class:`RumorVendorInteractAction`,
driven by each vendor's ``RumorVendor.chatter_table`` tag.
:class:`InnkeeperInteractAction` stays around because
:class:`BumpAction` and the existing test suite dispatch by
``isinstance(resolved, InnkeeperInteractAction)``. The subclass
preserves the historical ``innkeeper_id`` attribute so those
callers keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._rumor_vendor import RumorVendorInteractAction

if TYPE_CHECKING:
    from nhc.hexcrawl.model import HexWorld


class InnkeeperInteractAction(RumorVendorInteractAction):
    """Bump an innkeeper and hear a rumor from the overland pool."""

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
