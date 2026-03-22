"""Drapat — imp-like mischief creature. (BEB: Drapat)"""

from nhc.entities.components import AI, Health, LootTable, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("fell_spirit")
def create_fell_spirit() -> dict:
    return {
        "Renderable": Renderable(glyph="d", color="bright_red",
                                 render_order=2),
        "Description": creature_desc("fell_spirit"),
        "Stats": Stats(strength=0, dexterity=4, constitution=1),
        "Health": Health(current=7, maximum=7),
        "AI": AI(behavior="aggressive_melee", morale=6, faction="chaos"),
        "LootTable": LootTable(entries=[("gold", 0.5, "2d6")]),
    }
