"""Animated Armor — mindless construct, immune to mind effects. (BEB: Armadura animada)"""

from nhc.entities.components import (
    AI, BlocksMovement, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("animated_armor")
def create_animated_armor() -> dict:
    return {
        "Renderable": Renderable(glyph="A", color="cyan", render_order=2),
        "Description": creature_desc("animated_armor"),
        "Stats": Stats(strength=3, dexterity=0, constitution=3),
        "Health": Health(current=18, maximum=18),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="guard", morale=12, faction="construct"),
        "BlocksMovement": BlocksMovement(),
        "LootTable": LootTable(entries=[("shield", 0.2),
                                        ("sword", 0.15)]),
    }
