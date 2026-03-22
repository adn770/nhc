"""Llop (Wolf) — pack hunter. (BEB: Llop normal)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("llop")
def create_llop() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=2, constitution=1),
        "Health": Health(current=11, maximum=11),
        "Renderable": Renderable(glyph="w", color="white", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=6, faction="beast"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[]),
        "Description": creature_desc("llop"),
    }
