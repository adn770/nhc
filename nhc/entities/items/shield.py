"""Shield — defensive equipment."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("shield")
def create_shield() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": item_desc("shield"),
        "Armor": Armor(slot="shield", defense=1, slots=1),  # Tag component for armor bonus
    }
