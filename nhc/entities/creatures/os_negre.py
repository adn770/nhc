"""Os Negre (Black Bear) — forest-dwelling bear. (BEB: Os negre)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("os_negre")
def create_os_negre() -> dict:
    return {
        # Multi-attack (2×claw 1d3 + bite 1d6); simplified to bite + STR bonus
        "Stats": Stats(strength=3, dexterity=3, constitution=2),
        "Health": Health(current=18, maximum=18),
        "Renderable": Renderable(glyph="c", color="bright_black", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="beast"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[]),
        "Description": Description(
            name=t("creature.os_negre.name"),
            short=t("creature.os_negre.short"),
            long=t("creature.os_negre.long"),
        ),
    }
