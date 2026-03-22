"""Cuc de Tentacles (Tentacle Worm) — grasping cave predator. (BEB: Cuc de tentacles)"""

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


@EntityRegistry.register_creature("cuc_tentacles")
def create_cuc_tentacles() -> dict:
    return {
        "Renderable": Renderable(glyph="w", color="purple", render_order=2),
        "Description": Description(
            name=t("creature.cuc_tentacles.name"),
            short=t("creature.cuc_tentacles.short"),
            long=t("creature.cuc_tentacles.long"),
        ),
        "Stats": Stats(strength=2, dexterity=1),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }
