"""Item — crowbar."""

from nhc.entities.components import Throwable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("crowbar")
def create_crowbar() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="cyan", render_order=1),
        "Description": item_desc("crowbar"),
        "ForceTool": True,
        "Throwable": Throwable(),
    }
