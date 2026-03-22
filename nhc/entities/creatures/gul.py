"""Gul (Ghoul) — undead creature that drains life. (BEB: Gul)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Renderable,
    Stats,
    Undead,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("gul")
def create_gul() -> dict:
    return {
        "Renderable": Renderable(glyph="g", color="cyan", render_order=2),
        "Description": Description(
            name=t("creature.gul.name"),
            short=t("creature.gul.short"),
            long=t("creature.gul.long"),
        ),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d4"),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
        "Undead": Undead(),
        "DrainTouch": True,
    }
