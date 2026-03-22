"""Scroll of Charm Person — makes a humanoid fight for you. (BEB: Encisar persona)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_charm_person")
def create_scroll_charm_person() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": item_desc("scroll_charm_person"),
        # dice = duration in turns; targets nearest visible humanoid
        "Consumable": Consumable(effect="charm_person", dice="9", slots=1),
    }
