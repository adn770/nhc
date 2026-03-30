"""Scroll of Teleportation — blink to a random floor tile."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_teleportation")
def create_scroll_teleportation() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="magenta",
                                 render_order=1),
        "Description": item_desc("scroll_teleportation"),
        "Consumable": Consumable(effect="teleport", dice="1", slots=1),
    }
