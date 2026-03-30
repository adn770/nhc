"""Wand of Locking — locks doors."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import roll_dice


@EntityRegistry.register_item("wand_locking")
def create_wand_locking() -> dict:
    max_ch = roll_dice("2d10")
    return {
        "Renderable": Renderable(glyph="/", color="yellow",
                                 render_order=1),
        "Description": item_desc("wand_locking"),
        "Wand": Wand(effect="locking", charges=max_ch,
                     max_charges=max_ch),
    }
