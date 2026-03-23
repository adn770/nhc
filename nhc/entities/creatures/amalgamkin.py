"""Gentmalgama — mismatched chimera-creature. (BEB: Gentmalgama)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("amalgamkin")
def create_amalgamkin() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=3, constitution=0),
        "Health": Health(current=5, maximum=5),
        "Renderable": Renderable(glyph="m", color="bright_yellow", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="beast"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[("gold", 0.2, "1d4")]),
        "Description": creature_desc("amalgamkin"),
    }
