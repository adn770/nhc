"""Scroll of Web — entangles all visible creatures. (BEB: Teranyina)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_web")
def create_scroll_web() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="white", render_order=1),
        "Description": item_desc("scroll_web"),
        # dice = duration in turns; all visible creatures are webbed
        "Consumable": Consumable(effect="web", dice="1d4+1", slots=1),
    }
