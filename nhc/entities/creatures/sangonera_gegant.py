"""Sangonera Gegant (Giant Leech) — blood-draining swamp horror. (BEB: Sangonera gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    BloodDrain,
    Description,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("sangonera_gegant")
def create_sangonera_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="l", color="dark_red", render_order=2),
        "Description": Description(
            name=t("creature.sangonera_gegant.name"),
            short=t("creature.sangonera_gegant.short"),
            long=t("creature.sangonera_gegant.long"),
        ),
        "Stats": Stats(strength=1, dexterity=2),
        "Health": Health(current=9, maximum=9),
        "BloodDrain": BloodDrain(drain_per_hit=3),
        "AI": AI(behavior="aggressive_melee", morale=10),
        "BlocksMovement": BlocksMovement(),
    }
