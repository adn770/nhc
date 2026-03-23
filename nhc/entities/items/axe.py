"""Item — axe."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("axe")
def create_axe() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="white", render_order=1),
        "Description": item_desc("axe"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=2),
    }
