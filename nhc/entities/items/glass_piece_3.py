"""Worthless piece of glass #3."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("glass_piece_3")
def create_glass_piece_3() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="white", render_order=1),
        "Description": item_desc("glass_piece"),
        "Gem": Gem(value=0),
    }
