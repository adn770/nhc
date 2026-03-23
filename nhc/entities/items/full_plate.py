"""Item — full plate."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("full_plate")
def create_full_plate() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": item_desc("full_plate"),
        "Armor": Armor(slot="body", defense=16, slots=5),
    }
