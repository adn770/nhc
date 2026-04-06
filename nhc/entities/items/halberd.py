"""Item — halberd."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("halberd")
def create_halberd() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": item_desc("halberd"),
        "Weapon": Weapon(damage="1d10", type="melee", slots=2),
    }
