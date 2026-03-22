"""Llop d'Hivern (Winter Wolf) — frost breath on attacks. (BEB: Llop d'hivern)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    FrostBreath,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("llop_hivern")
def create_llop_hivern() -> dict:
    return {
        "Renderable": Renderable(glyph="W", color="bright_white", render_order=2),
        "Description": Description(
            name=t("creature.llop_hivern.name"),
            short=t("creature.llop_hivern.short"),
            long=t("creature.llop_hivern.long"),
        ),
        "Stats": Stats(strength=3, dexterity=3),
        "Health": Health(current=17, maximum=17),
        "Weapon": Weapon(damage="2d4"),
        "FrostBreath": FrostBreath(dice="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
    }
