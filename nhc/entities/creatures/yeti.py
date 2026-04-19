"""Yeti — icelands apex brute. (BEB-style: Yeti)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("yeti")
def create_yeti() -> dict:
    return {
        "Stats": Stats(strength=4, dexterity=3, constitution=3),
        "Health": Health(current=18, maximum=18),
        "Renderable": Renderable(glyph="Y", color="bright_white",
                                 render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=10, faction="beast"),
        "Weapon": Weapon(damage="1d10"),
        "LootTable": LootTable(entries=[("gold", 0.6, "3d6"),
                                        ("potion_frost", 0.15)]),
        "Description": creature_desc("yeti"),
    }
