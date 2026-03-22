"""Giant Eagle — powerful flying predator. (BEB: Àliga gegant)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_eagle")
def create_giant_eagle() -> dict:
    return {
        "Renderable": Renderable(glyph="E", color="yellow", render_order=2),
        "Description": creature_desc("giant_eagle"),
        "Stats": Stats(strength=3, dexterity=4, constitution=2),
        "Health": Health(current=18, maximum=18),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="beast"),
        "LootTable": LootTable(entries=[("gold", 0.3, "2d6")]),
    }
