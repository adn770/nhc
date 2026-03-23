"""Llangardanic (Lizardman) — scaled aquatic warrior. (BEB: Llangardanic)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("lizardman")
def create_lizardman() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=4, constitution=2),
        "Health": Health(current=10, maximum=10),
        "Renderable": Renderable(glyph="L", color="green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="humanoid"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[("gold", 0.5, "1d8"), ("short_sword", 0.15)]),
        "Description": creature_desc("lizardman"),
    }
