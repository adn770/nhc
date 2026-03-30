"""Wand of Death — instant kill, undead immune, 1-2 charges."""

from nhc.entities.components import Renderable, Wand
from nhc.entities.registry import EntityRegistry, item_desc
from nhc.utils.rng import roll_dice


@EntityRegistry.register_item("wand_death")
def create_wand_death() -> dict:
    max_ch = roll_dice("1d2")
    return {
        "Renderable": Renderable(glyph="/", color="bright_black",
                                 render_order=1),
        "Description": item_desc("wand_death"),
        "Wand": Wand(effect="death", charges=max_ch,
                     max_charges=max_ch),
    }
