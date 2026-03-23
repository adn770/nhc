"""Potion of Mind Vision — sense creatures through walls."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_mind_vision")
def create_potion_mind_vision() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="magenta", render_order=1),
        "Description": item_desc("potion_mind_vision"),
        "Consumable": Consumable(effect="detect_evil", dice="0", slots=1),
    }
