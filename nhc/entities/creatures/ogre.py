"""Ogre — massive, brutal giant. (BEB: Ogre)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("ogre")
def create_ogre() -> dict:
    return {
        "Stats": Stats(strength=4, dexterity=4, constitution=3),
        "Health": Health(current=19, maximum=19),
        "Renderable": Renderable(glyph="O", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=10, faction="giant"),
        "Weapon": Weapon(damage="1d10"),
        "LootTable": LootTable(entries=[("gold", 0.8, "4d6"), ("sword", 0.15)]),
        "Description": Description(
            name=t("creature.ogre.name"),
            short=t("creature.ogre.short"),
            long=t("creature.ogre.long"),
        ),
    }
