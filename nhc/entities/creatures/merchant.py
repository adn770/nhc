"""Merchant — non-combat NPC trader. (BEB: Mercader)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("merchant")
def create_merchant() -> dict:
    return {
        "Renderable": Renderable(glyph="@", color="bright_yellow",
                                 render_order=2),
        "Description": creature_desc("merchant"),
        "Stats": Stats(strength=1, dexterity=1, constitution=1,
                       intelligence=2, wisdom=2, charisma=3),
        "Health": Health(current=9, maximum=9),
        "AI": AI(behavior="idle", morale=4, faction="human"),
        "LootTable": LootTable(entries=[("gold", 1.0, "6d6"),
                                        ("potion_healing", 0.5),
                                        ("sword", 0.3)]),
    }
