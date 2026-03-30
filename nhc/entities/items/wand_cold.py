"""Wand of Cold — 2d6 cold damage."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import roll_dice


@EntityRegistry.register_item("wand_cold")
def create_wand_cold() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="bright_cyan",
                                 render_order=1),
        "Description": item_desc("wand_cold"),
        "Wand": Wand(effect="cold", charges=max_ch,
                     max_charges=max_ch),
    }
