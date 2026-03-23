"""Wand of Magic Missile — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_magic_missile")
def create_wand_magic_missile() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="bright_yellow", render_order=1),
        "Description": item_desc("wand_magic_missile"),
        "Wand": Wand(effect="magic_missile", charges=max_ch, max_charges=max_ch),
    }
