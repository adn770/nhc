"""Wand of Opening — opens locked doors."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import roll_dice


@EntityRegistry.register_item("wand_opening")
def create_wand_opening() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="bright_white",
                                 render_order=1),
        "Description": item_desc("wand_opening"),
        "Wand": Wand(effect="opening", charges=max_ch,
                     max_charges=max_ch),
    }
