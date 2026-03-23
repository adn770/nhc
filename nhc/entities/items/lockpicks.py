"""Item — lockpicks."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("lockpicks")
def create_lockpicks() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="grey", render_order=1),
        "Description": item_desc("lockpicks"),
    }
