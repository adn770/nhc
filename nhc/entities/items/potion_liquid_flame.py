"""Potion of Liquid Flame — deals fire damage to nearby creatures."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_liquid_flame")
def create_potion_liquid_flame() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_red", render_order=1),
        "Description": item_desc("potion_liquid_flame"),
        "Consumable": Consumable(effect="fireball", dice="2d6", slots=1),
    }
