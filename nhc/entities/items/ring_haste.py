"""Ring of Haste — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_haste")
def create_ring_haste() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_red", render_order=1),
        "Description": item_desc("ring_haste"),
        "Ring": Ring(effect="haste"),
    }
