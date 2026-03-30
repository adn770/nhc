"""Scroll of Enchant Armor — +1 magic bonus to worn armor."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_enchant_armor")
def create_scroll_enchant_armor() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan",
                                 render_order=1),
        "Description": item_desc("scroll_enchant_armor"),
        "Consumable": Consumable(effect="enchant_armor", dice="1",
                                 slots=1),
    }
