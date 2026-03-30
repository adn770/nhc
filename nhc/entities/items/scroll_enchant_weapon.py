"""Scroll of Enchant Weapon — +1 magic bonus to wielded weapon."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_enchant_weapon")
def create_scroll_enchant_weapon() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_yellow",
                                 render_order=1),
        "Description": item_desc("scroll_enchant_weapon"),
        "Consumable": Consumable(effect="enchant_weapon", dice="1",
                                 slots=1),
    }
