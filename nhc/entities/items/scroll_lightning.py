"""Scroll of Lightning Bolt — ranged damage consumable."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_lightning")
def create_scroll_lightning() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": item_desc("scroll_lightning"),
        "Consumable": Consumable(effect="damage_nearest", dice="3d6", slots=1),
    }
