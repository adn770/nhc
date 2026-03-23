"""Crossbow — heavy ranged weapon."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("crossbow")
def create_crossbow() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": item_desc("crossbow"),
        "Weapon": Weapon(damage="1d8", type="ranged", slots=3),
    }
