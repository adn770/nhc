"""Osgo (Bugbear) — hulking, stealthy goblinoid. (BEB: Osgo)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("bugbear")
def create_bugbear() -> dict:
    return {
        "Stats": Stats(strength=3, dexterity=4, constitution=2),
        "Health": Health(current=14, maximum=14),
        "Renderable": Renderable(glyph="B", color="yellow", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="goblinoid"),
        # 2d4 damage; modelled as 1d6 + STR 3
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[("gold", 0.6, "2d8"), ("sword", 0.2)]),
        "Description": creature_desc("bugbear"),
    }
