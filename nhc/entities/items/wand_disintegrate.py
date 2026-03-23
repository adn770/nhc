"""Wand of Disintegrate — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_disintegrate")
def create_wand_disintegrate() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="bright_cyan", render_order=1),
        "Description": item_desc("wand_disintegrate"),
        "Wand": Wand(effect="disintegrate", charges=max_ch, max_charges=max_ch),
    }
