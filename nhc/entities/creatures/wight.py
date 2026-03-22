"""Wight — undead level-drainer. (BEB: Entitat)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Undead,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("wight")
def create_wight() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=13, maximum=13),  # 3 HD average
        "Renderable": Renderable(glyph="W", color="bright_black",
                                 render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="undead"),
        "LootTable": LootTable(entries=[("gold", 0.4, "2d6")]),
        "Undead": Undead(),
        # DrainTouch: on hit drains XP and max HP
        "DrainTouch": True,
        "Description": Description(
            name=t("creature.wight.name"),
            short=t("creature.wight.short"),
            long=t("creature.wight.long"),
        ),
    }
