"""Wand of Amok — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_amok")
def create_wand_amok() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="magenta", render_order=1),
        "Description": item_desc("wand_amok"),
        "Wand": Wand(effect="amok", charges=max_ch, max_charges=max_ch),
    }
