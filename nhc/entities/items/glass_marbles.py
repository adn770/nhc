"""Item — glass marbles."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("glass_marbles")
def create_glass_marbles() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_cyan", render_order=1),
        "Description": item_desc("glass_marbles"),
    }
