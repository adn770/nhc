"""Wand of Cancellation — strips all magical effects."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import roll_dice


@EntityRegistry.register_item("wand_cancellation")
def create_wand_cancellation() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="white",
                                 render_order=1),
        "Description": item_desc("wand_cancellation"),
        "Wand": Wand(effect="cancellation", charges=max_ch,
                     max_charges=max_ch),
    }
