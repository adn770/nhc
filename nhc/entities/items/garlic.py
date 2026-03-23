"""Garlic — repels undead creatures."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("garlic")
def create_garlic() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_white", render_order=1),
        "Description": item_desc("garlic"),
    }
