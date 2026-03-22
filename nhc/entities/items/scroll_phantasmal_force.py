"""Scroll of Phantasmal Force — confuses enemies. (BEB: Força fantasmal)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_phantasmal_force")
def create_scroll_phantasmal_force() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="magenta", render_order=1),
        "Description": item_desc("scroll_phantasmal_force"),
        "Consumable": Consumable(effect="phantasmal_force", dice="6", slots=1),
    }
