"""Temple actions — interact with a priest, buy services and goods."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions._base import Action
from nhc.core.events import Event, MessageEvent, TempleMenuEvent
from nhc.entities.components import StatusEffect
from nhc.i18n import t
from nhc.rules.prices import temple_service_price

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


# Bless duration in turns (game uses turns, not rounds).
BLESS_DURATION = 60


class TempleInteractAction(Action):
    """Bumping a priest opens the temple menu (free action)."""

    def __init__(self, actor: int, priest: int) -> None:
        super().__init__(actor)
        self.priest = priest

    async def validate(self, world: "World", level: "Level") -> bool:
        ts = world.get_component(self.priest, "TempleServices")
        if not ts:
            return False
        apos = world.get_component(self.actor, "Position")
        ppos = world.get_component(self.priest, "Position")
        if not apos or not ppos:
            return False
        return abs(apos.x - ppos.x) <= 1 and abs(apos.y - ppos.y) <= 1

    async def execute(
        self, world: "World", level: "Level",
    ) -> list[Event]:
        return [TempleMenuEvent(priest=self.priest)]


class TempleServiceAction(Action):
    """Pay the priest to perform a service on the actor.

    Supported service IDs: ``heal``, ``remove_curse``, ``bless``.
    """

    def __init__(
        self, actor: int, priest: int, service_id: str,
    ) -> None:
        super().__init__(actor)
        self.priest = priest
        self.service_id = service_id
        self._fail_reason = ""

    @property
    def fail_reason(self) -> str:
        return self._fail_reason

    async def validate(self, world: "World", level: "Level") -> bool:
        ts = world.get_component(self.priest, "TempleServices")
        if not ts or self.service_id not in ts.services:
            self._fail_reason = "not_offered"
            return False

        player = world.get_component(self.actor, "Player")
        if not player:
            return False

        price = temple_service_price(self.service_id, level.depth)
        if player.gold < price:
            self._fail_reason = "cannot_afford"
            return False

        # Service-specific preconditions
        if self.service_id == "heal":
            health = world.get_component(self.actor, "Health")
            if health and health.current >= health.maximum:
                self._fail_reason = "already_full_hp"
                return False
        elif self.service_id == "remove_curse":
            if not world.has_component(self.actor, "Cursed"):
                self._fail_reason = "no_curse"
                return False
        elif self.service_id == "bless":
            status = world.get_component(self.actor, "StatusEffect")
            if status and status.blessed >= BLESS_DURATION:
                self._fail_reason = "already_blessed"
                return False
        return True

    async def execute(
        self, world: "World", level: "Level",
    ) -> list[Event]:
        player = world.get_component(self.actor, "Player")
        price = temple_service_price(self.service_id, level.depth)
        player.gold -= price

        events: list[Event] = []
        if self.service_id == "heal":
            health = world.get_component(self.actor, "Health")
            if health:
                health.current = health.maximum
            events.append(MessageEvent(
                text=t("temple.heal_done", price=price),
            ))
        elif self.service_id == "remove_curse":
            world.remove_component(self.actor, "Cursed")
            events.append(MessageEvent(
                text=t("temple.remove_curse_done", price=price),
            ))
        elif self.service_id == "bless":
            status = world.get_component(self.actor, "StatusEffect")
            if status is None:
                world.add_component(
                    self.actor, "StatusEffect",
                    StatusEffect(blessed=BLESS_DURATION),
                )
            else:
                status.blessed = max(status.blessed, BLESS_DURATION)
            events.append(MessageEvent(
                text=t("temple.bless_done",
                       price=price, turns=BLESS_DURATION),
            ))
        return events
