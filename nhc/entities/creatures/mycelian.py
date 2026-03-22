"""Mycelian — intelligent fungal creature. (BEB: Micèlic)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("mycelian")
def create_mycelian() -> dict:
    return {
        "Renderable": Renderable(glyph="M", color="magenta", render_order=2),
        "Description": creature_desc("mycelian"),
        "Stats": Stats(strength=2, dexterity=1, constitution=2,
                       intelligence=2, wisdom=2),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="guard", morale=9, faction="plant"),
        "LootTable": LootTable(entries=[("gold", 0.4, "2d6")]),
    }
