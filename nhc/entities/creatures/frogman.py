"""Granyotic (Frogman) — amphibious humanoid. (BEB: Granyotic)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("frogman")
def create_frogman() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=4, constitution=1),
        "Health": Health(current=4, maximum=4),
        "Renderable": Renderable(glyph="f", color="green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="humanoid"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[("gold", 0.4, "1d6")]),
        "Description": creature_desc("frogman"),
    }
