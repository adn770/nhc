"""Werewolf — cursed shapeshifter, vulnerable to silver. (BEB: Licàntrop llop)"""

from nhc.entities.components import (
    AI, BlocksMovement, Health, LootTable, Renderable,
    RequiresMagicWeapon, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("werewolf")
def create_werewolf() -> dict:
    return {
        "Renderable": Renderable(glyph="W", color="bright_yellow",
                                 render_order=2),
        "Description": creature_desc("werewolf"),
        "Stats": Stats(strength=3, dexterity=3, constitution=3),
        "Health": Health(current=18, maximum=18),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="beast"),
        "BlocksMovement": BlocksMovement(),
        "RequiresMagicWeapon": RequiresMagicWeapon(),
        "LootTable": LootTable(entries=[("gold", 0.6, "3d6"),
                                        ("sword", 0.15)]),
    }
