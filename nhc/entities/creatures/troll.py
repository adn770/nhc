"""Troll — regenerating monster. (BEB: Trol)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Regeneration,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("troll")
def create_troll() -> dict:
    return {
        "Renderable": Renderable(glyph="T", color="green", render_order=2),
        "Description": Description(
            name=t("creature.troll.name"),
            short=t("creature.troll.short"),
            long=t("creature.troll.long"),
        ),
        "Stats": Stats(strength=4, dexterity=2),
        "Health": Health(current=22, maximum=22),
        "Weapon": Weapon(damage="1d8"),
        "Regeneration": Regeneration(hp_per_turn=3),
        "AI": AI(behavior="aggressive_melee", morale=10),
        "BlocksMovement": BlocksMovement(),
    }
