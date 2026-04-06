"""Gnoll — hyena-headed chaotic humanoid. (BEB: Gnoll)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("gnoll")
def create_gnoll() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=1, constitution=2,
                       intelligence=0, wisdom=0, charisma=-1),
        "Health": Health(current=9, maximum=9),  # 2 HD average
        "Renderable": Renderable(glyph="G", color="bright_yellow",
                                 render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="gnoll"),
        "LootTable": LootTable(entries=[("gold", 0.6, "3d6"),
                                        ("spear", 0.2),
                                        ("shield", 0.1)]),
        "Description": creature_desc("gnoll"),
    }
