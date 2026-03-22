"""Escorpí Gegant (Giant Scorpion) — venomous arachnid. (BEB: Escorpí gegant)"""

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


@EntityRegistry.register_creature("escorpi_gegant")
def create_escorpi_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="s", color="yellow", render_order=2),
        "Description": Description(
            name=t("creature.escorpi_gegant.name"),
            short=t("creature.escorpi_gegant.short"),
            long=t("creature.escorpi_gegant.long"),
        ),
        "Stats": Stats(strength=3, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=11),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }
