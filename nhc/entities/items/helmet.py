"""Item — helmet."""

from nhc.entities.components import Throwable, Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("helmet")
def create_helmet() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="cyan", render_order=1),
        "Description": item_desc("helmet"),
        "Armor": Armor(slot="helmet", defense=1, slots=1),
        "Throwable": Throwable(),
    }
