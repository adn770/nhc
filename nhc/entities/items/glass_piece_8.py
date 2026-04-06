"""Worthless piece of glass #8."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("glass_piece_8")
def create_glass_piece_8() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="white", render_order=1),
        "Description": item_desc("glass_piece"),
        "Gem": Gem(value=0),
    }
