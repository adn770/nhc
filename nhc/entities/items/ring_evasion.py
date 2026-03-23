"""Ring of Evasion — description."""

from nhc.entities.components import Renderable, Ring
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("ring_evasion")
def create_ring_evasion() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="magenta", render_order=1),
        "Description": item_desc("ring_evasion"),
        "Ring": Ring(effect="evasion"),
    }
