"""Uarg (Warg) — massive, intelligent dire wolf. (BEB: Uarg)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("uarg")
def create_uarg() -> dict:
    return {
        "Stats": Stats(strength=5, dexterity=4, constitution=3),
        "Health": Health(current=25, maximum=25),
        "Renderable": Renderable(glyph="U", color="white", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=10, faction="beast"),
        "Weapon": Weapon(damage="3d6"),
        "LootTable": LootTable(entries=[("gold", 0.1, "1d4")]),
        "Description": Description(
            name=t("creature.uarg.name"),
            short=t("creature.uarg.short"),
            long=t("creature.uarg.long"),
        ),
    }
