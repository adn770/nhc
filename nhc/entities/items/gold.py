"""Gold coins — currency."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gold")
def create_gold() -> dict:
    return {
        "Renderable": Renderable(glyph="$", color="bright_yellow", render_order=1),
        "Description": item_desc("gold"),
        "Gold": True,  # Tag component
    }
