"""Banshee — spectral undead with a killing wail. (BEB: Banshee)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    DeathWail,
    Description,
    Health,
    Renderable,
    RequiresMagicWeapon,
    Stats,
    Undead,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("banshee")
def create_banshee() -> dict:
    return {
        "Renderable": Renderable(glyph="B", color="bright_cyan", render_order=2),
        "Description": Description(
            name=t("creature.banshee.name"),
            short=t("creature.banshee.short"),
            long=t("creature.banshee.long"),
        ),
        "Stats": Stats(strength=2, dexterity=4),
        "Health": Health(current=25, maximum=25),
        "DeathWail": DeathWail(radius=5, save_dc=15),
        "RequiresMagicWeapon": RequiresMagicWeapon(),
        "AI": AI(behavior="aggressive_melee", morale=12),
        "BlocksMovement": BlocksMovement(),
        "Undead": Undead(),
    }
