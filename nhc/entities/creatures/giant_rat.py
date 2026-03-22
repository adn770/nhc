"""Giant Rat — weak, fast vermin."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_rat")
def create_giant_rat() -> dict:
    return {
        "Stats": Stats(strength=0, dexterity=3, constitution=0),
        "Health": Health(current=2, maximum=2),
        "Renderable": Renderable(glyph="r", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=4, faction="vermin"),
        "LootTable": LootTable(entries=[]),
        "Description": creature_desc("giant_rat"),
    }
