"""Wand of Digging — carves through walls."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import roll_dice


@EntityRegistry.register_item("wand_digging")
def create_wand_digging() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="yellow",
                                 render_order=1),
        "Description": item_desc("wand_digging"),
        "Wand": Wand(effect="digging", charges=max_ch,
                     max_charges=max_ch),
    }
