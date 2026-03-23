"""Ring of Elements — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_elements")
def create_ring_elements() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_blue", render_order=1),
        "Description": item_desc("ring_elements"),
        "Ring": Ring(effect="elements"),
    }
