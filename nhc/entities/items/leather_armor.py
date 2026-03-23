"""Leather Armor — light protection."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("leather_armor")
def create_leather_armor() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="yellow", render_order=1),
        "Description": item_desc("leather_armor"),
        "Shield": True,
    }
