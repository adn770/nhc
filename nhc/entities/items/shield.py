"""Shield — defensive equipment."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("shield")
def create_shield() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": item_desc("shield"),
        "Shield": True,  # Tag component for armor bonus
    }
