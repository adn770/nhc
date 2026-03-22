"""Gargoyle — stone creature immune to non-magic weapons. (BEB: Gàrgola)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    RequiresMagicWeapon,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("gargoyle")
def create_gargoyle() -> dict:
    return {
        "Renderable": Renderable(glyph="G", color="grey", render_order=2),
        "Description": creature_desc("gargoyle"),
        "Stats": Stats(strength=3, dexterity=3),
        "Health": Health(current=17, maximum=17),
        "Weapon": Weapon(damage="1d6"),
        "RequiresMagicWeapon": RequiresMagicWeapon(),
        "AI": AI(behavior="aggressive_melee", morale=11),
        "BlocksMovement": BlocksMovement(),
    }
