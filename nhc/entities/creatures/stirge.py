"""Stirge — blood-draining flying pest. (BEB: Estirge)"""

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


@EntityRegistry.register_creature("stirge")
def create_stirge() -> dict:
    return {
        "Renderable": Renderable(glyph="s", color="red", render_order=2),
        "Description": Description(
            name=t("creature.stirge.name"),
            short=t("creature.stirge.short"),
            long=t("creature.stirge.long"),
        ),
        "Stats": Stats(strength=1, dexterity=4),
        "Health": Health(current=4, maximum=4),
        "BloodDrain": BloodDrain(drain_per_hit=2),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
    }
