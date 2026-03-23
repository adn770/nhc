"""Wand of Firebolt — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_firebolt")
def create_wand_firebolt() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="green", render_order=1),
        "Description": item_desc("wand_firebolt"),
        "Wand": Wand(effect="firebolt", charges=max_ch, max_charges=max_ch),
    }
