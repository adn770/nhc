"""Wererat — sneaky lycanthrope, lurks in sewers. (BEB: Licàntrop rata)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, RequiresMagicWeapon, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("wererat")
def create_wererat() -> dict:
    return {
        "Renderable": Renderable(glyph="R", color="grey", render_order=2),
        "Description": creature_desc("wererat"),
        "Stats": Stats(strength=2, dexterity=4, constitution=2),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="beast"),
        "RequiresMagicWeapon": RequiresMagicWeapon(),
        "LootTable": LootTable(entries=[("gold", 0.7, "2d6"),
                                        ("dagger", 0.2)]),
    }
