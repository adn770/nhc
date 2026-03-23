"""Item — plate cuirass."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("plate_cuirass")
def create_plate_cuirass() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="white", render_order=1),
        "Description": item_desc("plate_cuirass"),
        "Shield": True,
    }
