"""Ring of Mending — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_mending")
def create_ring_mending() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_white", render_order=1),
        "Description": item_desc("ring_mending"),
        "Ring": Ring(effect="mending"),
    }
