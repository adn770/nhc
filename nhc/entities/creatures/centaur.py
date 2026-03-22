"""Centaur — noble half-horse warrior with lance charge. (BEB: Centaure)"""

from nhc.entities.components import (
    AI, BlocksMovement, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("centaur")
def create_centaur() -> dict:
    return {
        "Renderable": Renderable(glyph="C", color="yellow", render_order=2),
        "Description": creature_desc("centaur"),
        "Stats": Stats(strength=4, dexterity=2, constitution=3,
                       wisdom=2),
        "Health": Health(current=18, maximum=18),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="guard", morale=8, faction="neutral"),
        "BlocksMovement": BlocksMovement(),
        "LootTable": LootTable(entries=[("gold", 0.6, "3d6"),
                                        ("short_sword", 0.2)]),
    }
