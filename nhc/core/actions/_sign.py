"""Wayside rumour-sign interactions.

:class:`SignReadAction` reads a rumour from the overland pool when
the player bumps a :class:`RumorSign` entity. An empty pool emits
a localized "no news" beat.
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


class SignReadAction(Action):
    """Read a rumour off a wayside signpost.

    Mirrors :class:`InnkeeperInteractAction`: consumes the head of
    :attr:`HexWorld.active_rumors` via
    :func:`nhc.hexcrawl.rumor_pool.consume_rumor` and emits a
    :class:`MessageEvent` with the rumour text. An empty pool
    yields ``action.sign_read.no_news`` so the bump still gets
    feedback.
    """

    def __init__(
        self,
        actor: int,
        sign_id: int,
        hex_world: "HexWorld | None" = None,
    ) -> None:
        super().__init__(actor)
        self.sign_id = sign_id
        self.hex_world = hex_world

    async def validate(self, world: "World", level: "Level") -> bool:
        if not world.has_component(self.sign_id, "RumorSign"):
            return False
        apos = world.get_component(self.actor, "Position")
        spos = world.get_component(self.sign_id, "Position")
        if apos is None or spos is None:
            return False
        return (
            abs(apos.x - spos.x) <= 1 and abs(apos.y - spos.y) <= 1
        )

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.hexcrawl.rumor_pool import (
            consume_rumor,
            has_settlement_in_reach,
            seed_wilderness_rumor_pool,
        )

        if self.hex_world is None:
            return [MessageEvent(text=t("action.sign_read.no_news"))]
        rumor = consume_rumor(self.hex_world)
        if rumor is None:
            # Wilderness fallback: if the surrounding macro hex has
            # no settlement in reach to seed a proper rumour pool,
            # seed 1-2 nature/travel flavor rumours so the signpost
            # is never silent.
            macro = self.hex_world.exploring_hex
            if (macro is not None
                    and not has_settlement_in_reach(
                        self.hex_world, macro,
                    )):
                seed_wilderness_rumor_pool(
                    self.hex_world,
                    world_seed=self.hex_world.seed,
                    macro_coord=macro,
                    count=2,
                )
                rumor = consume_rumor(self.hex_world)
            if rumor is None:
                return [
                    MessageEvent(text=t("action.sign_read.no_news")),
                ]
        logger.info(
            "Sign shared rumor %s (truth=%s)",
            rumor.id, rumor.truth,
        )
        return [MessageEvent(text=rumor.text)]
