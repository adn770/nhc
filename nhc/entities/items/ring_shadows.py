"""Ring of Shadows — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_shadows")
def create_ring_shadows() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_yellow", render_order=1),
        "Description": item_desc("ring_shadows"),
        "Ring": Ring(effect="shadows"),
    }
