"""Wand of Lightning — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_lightning")
def create_wand_lightning() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="yellow", render_order=1),
        "Description": item_desc("wand_lightning"),
        "Wand": Wand(effect="lightning", charges=max_ch, max_charges=max_ch),
    }
