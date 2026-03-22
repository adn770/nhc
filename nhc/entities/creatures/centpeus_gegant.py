"""Centpeus Gegant (Giant Centipede) — weak venom. (BEB: Centpeus gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("centpeus_gegant")
def create_centpeus_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="c", color="dark_green", render_order=2),
        "Description": Description(
            name=t("creature.centpeus_gegant.name"),
            short=t("creature.centpeus_gegant.short"),
            long=t("creature.centpeus_gegant.long"),
        ),
        "Stats": Stats(strength=-1, dexterity=4),
        "Health": Health(current=2, maximum=2),
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }
