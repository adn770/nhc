"""Item — blank book."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("blank_book")
def create_blank_book() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("blank_book"),
    }
