"""Wand of Slowness — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_slowness")
def create_wand_slowness() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="bright_green", render_order=1),
        "Description": item_desc("wand_slowness"),
        "Wand": Wand(effect="slowness", charges=max_ch, max_charges=max_ch),
    }
