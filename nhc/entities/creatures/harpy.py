"""Harpy — enchanting song forces victims to approach. (BEB: Harpia)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    CharmSong,
    Description,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("harpy")
def create_harpy() -> dict:
    return {
        "Renderable": Renderable(glyph="H", color="magenta", render_order=2),
        "Description": Description(
            name=t("creature.harpy.name"),
            short=t("creature.harpy.short"),
            long=t("creature.harpy.long"),
        ),
        "Stats": Stats(strength=2, dexterity=4),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "CharmSong": CharmSong(radius=6, save_dc=12),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
    }
