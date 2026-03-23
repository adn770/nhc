"""Llop Terrible (Dire Wolf) — enormous predatory wolf. (BEB: Llop terrible)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("dire_wolf")
def create_dire_wolf() -> dict:
    return {
        "Stats": Stats(strength=4, dexterity=3, constitution=2),
        "Health": Health(current=19, maximum=19),
        "Renderable": Renderable(glyph="d", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="beast"),
        "Weapon": Weapon(damage="2d4"),
        "LootTable": LootTable(entries=[]),
        "Description": creature_desc("dire_wolf"),
    }
