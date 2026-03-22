"""Cocatriu (Cockatrice) — touch petrifies. (BEB: Cocatriu)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    PetrifyingTouch,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("cocatriu")
def create_cocatriu() -> dict:
    return {
        "Renderable": Renderable(glyph="c", color="yellow", render_order=2),
        "Description": Description(
            name=t("creature.cocatriu.name"),
            short=t("creature.cocatriu.short"),
            long=t("creature.cocatriu.long"),
        ),
        "Stats": Stats(strength=1, dexterity=3),
        "Health": Health(current=17, maximum=17),
        "Weapon": Weapon(damage="1d6"),
        "PetrifyingTouch": PetrifyingTouch(),
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
    }
