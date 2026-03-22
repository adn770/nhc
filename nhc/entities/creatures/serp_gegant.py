"""Serp Gegant (Giant Snake) — constricting venomous serpent. (BEB: Serp gegant)"""

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


@EntityRegistry.register_creature("serp_gegant")
def create_serp_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="S", color="green", render_order=2),
        "Description": Description(
            name=t("creature.serp_gegant.name"),
            short=t("creature.serp_gegant.short"),
            long=t("creature.serp_gegant.long"),
        ),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=11, maximum=11),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }
