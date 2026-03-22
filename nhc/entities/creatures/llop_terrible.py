"""Llop Terrible (Dire Wolf) — enormous predatory wolf. (BEB: Llop terrible)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("llop_terrible")
def create_llop_terrible() -> dict:
    return {
        "Stats": Stats(strength=4, dexterity=3, constitution=2),
        "Health": Health(current=19, maximum=19),
        "Renderable": Renderable(glyph="d", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="beast"),
        "Weapon": Weapon(damage="2d4"),
        "LootTable": LootTable(entries=[]),
        "Description": Description(
            name=t("creature.llop_terrible.name"),
            short=t("creature.llop_terrible.short"),
            long=t("creature.llop_terrible.long"),
        ),
    }
