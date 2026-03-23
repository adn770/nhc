"""Wand of Poison — description."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import get_rng, roll_dice


@EntityRegistry.register_item("wand_poison")
def create_wand_poison() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="bright_red", render_order=1),
        "Description": item_desc("wand_poison"),
        "Wand": Wand(effect="poison", charges=max_ch, max_charges=max_ch),
    }
