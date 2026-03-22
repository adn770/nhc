"""Spectre — powerful undead that drains life force. (BEB: Espectre)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Undead,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("spectre")
def create_spectre() -> dict:
    return {
        "Stats": Stats(strength=3, dexterity=4, constitution=3),
        "Health": Health(current=27, maximum=27),  # 6 HD average
        "Renderable": Renderable(glyph="S", color="bright_cyan",
                                 render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=11, faction="undead"),
        "LootTable": LootTable(entries=[("gold", 0.5, "4d6")]),
        "Undead": Undead(),
        # DrainTouch: on hit drains XP and max HP (stronger than wight)
        "DrainTouch": True,
        "Description": creature_desc("spectre"),
    }
