"""Item — bellows."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("bellows")
def create_bellows() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="yellow", render_order=1),
        "Description": item_desc("bellows"),
    }
