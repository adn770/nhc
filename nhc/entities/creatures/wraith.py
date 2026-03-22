"""Wraith — incorporeal undead that drains life force. (BEB: Aparegut)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, RequiresMagicWeapon, Stats, Undead,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("wraith")
def create_wraith() -> dict:
    return {
        "Renderable": Renderable(glyph="W", color="bright_white", render_order=2),
        "Description": creature_desc("wraith"),
        "Stats": Stats(strength=3, dexterity=3, constitution=3),
        "Health": Health(current=16, maximum=16),
        "AI": AI(behavior="aggressive_melee", morale=11, faction="undead"),
        "LootTable": LootTable(entries=[("gold", 0.4, "3d6")]),
        "Undead": Undead(),
        "RequiresMagicWeapon": RequiresMagicWeapon(),
        "DrainTouch": True,
    }
