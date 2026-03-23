"""Holy Symbol — required for turning undead."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("holy_symbol")
def create_holy_symbol() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow", render_order=1),
        "Description": item_desc("holy_symbol"),
    }
