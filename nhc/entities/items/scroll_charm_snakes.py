"""Scroll of Charm Snakes — pacifies serpent-type enemies. (BEB: Encantar serps)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_charm_snakes")
def create_scroll_charm_snakes() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="green", render_order=1),
        "Description": item_desc("scroll_charm_snakes"),
        "Consumable": Consumable(effect="charm_snakes", dice="6", slots=1),
    }
