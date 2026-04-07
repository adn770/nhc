"""Werebear — powerful lycanthrope, sometimes friendly. (BEB: Licàntrop os)"""

from nhc.entities.components import (
    AI, BlocksMovement, Health, LootTable, Renderable,
    RequiresMagicWeapon, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("werebear")
def create_werebear() -> dict:
    return {
        "Renderable": Renderable(glyph="B", color="bright_yellow",
                                 render_order=2),
        "Description": creature_desc("werebear"),
        "Stats": Stats(strength=5, dexterity=2, constitution=4),
        "Health": Health(current=27, maximum=27),
        "Weapon": Weapon(damage="1d10"),
        "AI": AI(behavior="guard", morale=10, faction="neutral"),
        "BlocksMovement": BlocksMovement(),
        "RequiresMagicWeapon": RequiresMagicWeapon(),
        "LootTable": LootTable(entries=[("gold", 0.5, "4d6"),
                                        ("potion_healing", 0.3)]),
    }
