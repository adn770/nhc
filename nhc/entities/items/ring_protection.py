"""Ring of Protection — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_protection")
def create_ring_protection() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_black", render_order=1),
        "Description": item_desc("ring_protection"),
        "Ring": Ring(effect="protection"),
    }
