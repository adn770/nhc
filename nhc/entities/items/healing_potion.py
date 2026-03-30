"""Healing Potion — restores hit points."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("healing_potion")
def create_healing_potion() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="red", render_order=1),
        "Description": item_desc("healing_potion"),
        "Consumable": Consumable(effect="heal", dice="2d4+2", slots=1),
        "Throwable": Throwable(),
    }
