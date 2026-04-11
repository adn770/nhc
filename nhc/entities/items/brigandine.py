"""Item — brigandine."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("brigandine")
def create_brigandine() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_yellow", render_order=1),
        "Description": item_desc("brigandine"),
        "Armor": Armor(slot="body", defense=13, slots=2),
    }
