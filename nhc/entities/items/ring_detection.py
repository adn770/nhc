"""Ring of Detection — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_detection")
def create_ring_detection() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_green", render_order=1),
        "Description": item_desc("ring_detection"),
        "Ring": Ring(effect="detection"),
    }
