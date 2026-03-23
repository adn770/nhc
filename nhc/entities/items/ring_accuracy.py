"""Ring of Accuracy — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_accuracy")
def create_ring_accuracy() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_cyan", render_order=1),
        "Description": item_desc("ring_accuracy"),
        "Ring": Ring(effect="accuracy"),
    }
