"""Scroll of Mirror Image — creates 1d4 illusions that absorb hits. (BEB: Imatge mirall)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_mirror_image")
def create_scroll_mirror_image() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="cyan", render_order=1),
        "Description": item_desc("scroll_mirror_image"),
        # dice = number of images created (1d4)
        "Consumable": Consumable(effect="mirror_image", dice="1d4", slots=1),
    }
