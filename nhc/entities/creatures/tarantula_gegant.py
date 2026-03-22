"""Taràntula Gegant (Giant Tarantula) — venomous spider. (BEB: Taràntula gegant)"""

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


@EntityRegistry.register_creature("tarantula_gegant")
def create_tarantula_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="S", color="brown", render_order=2),
        "Description": Description(
            name=t("creature.tarantula_gegant.name"),
            short=t("creature.tarantula_gegant.short"),
            long=t("creature.tarantula_gegant.long"),
        ),
        "Stats": Stats(strength=1, dexterity=4),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }
