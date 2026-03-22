"""Owlbear — ferocious hybrid predator. (BEB: Os oliba)"""

from nhc.entities.components import (
    AI, BlocksMovement, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("owlbear")
def create_owlbear() -> dict:
    return {
        "Renderable": Renderable(glyph="O", color="yellow", render_order=2),
        "Description": creature_desc("owlbear"),
        "Stats": Stats(strength=4, dexterity=1, constitution=3),
        "Health": Health(current=22, maximum=22),
        "Weapon": Weapon(damage="1d10"),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="beast"),
        "BlocksMovement": BlocksMovement(),
        "LootTable": LootTable(entries=[("gold", 0.5, "3d6")]),
    }
