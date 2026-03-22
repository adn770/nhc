"""Wyvern — venomous draconic beast. (BEB: Víbria)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("wyvern")
def create_wyvern() -> dict:
    return {
        "Renderable": Renderable(glyph="V", color="dark_green", render_order=2),
        "Description": Description(
            name=t("creature.wyvern.name"),
            short=t("creature.wyvern.short"),
            long=t("creature.wyvern.long"),
        ),
        "Stats": Stats(strength=5, dexterity=3),
        "Health": Health(current=28, maximum=28),
        "Weapon": Weapon(damage="2d6"),
        "VenomousStrike": True,
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
    }
