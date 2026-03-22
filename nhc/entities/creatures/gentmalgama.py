"""Gentmalgama — mismatched chimera-creature. (BEB: Gentmalgama)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("gentmalgama")
def create_gentmalgama() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=3, constitution=0),
        "Health": Health(current=5, maximum=5),
        "Renderable": Renderable(glyph="m", color="bright_yellow", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="beast"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[("gold", 0.2, "1d4")]),
        "Description": Description(
            name=t("creature.gentmalgama.name"),
            short=t("creature.gentmalgama.short"),
            long=t("creature.gentmalgama.long"),
        ),
    }
