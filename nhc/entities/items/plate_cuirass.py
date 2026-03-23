"""Item — plate cuirass."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("plate_cuirass")
def create_plate_cuirass() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="white", render_order=1),
        "Description": item_desc("plate_cuirass"),
        "Armor": Armor(slot="body", defense=15, slots=4),
    }
