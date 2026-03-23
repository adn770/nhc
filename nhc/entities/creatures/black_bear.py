"""Os Negre (Black Bear) — forest-dwelling bear. (BEB: Os negre)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("black_bear")
def create_black_bear() -> dict:
    return {
        # Multi-attack (2×claw 1d3 + bite 1d6); simplified to bite + STR bonus
        "Stats": Stats(strength=3, dexterity=3, constitution=2),
        "Health": Health(current=18, maximum=18),
        "Renderable": Renderable(glyph="c", color="bright_black", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="beast"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[]),
        "Description": creature_desc("black_bear"),
    }
