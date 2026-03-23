"""Item — club."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("club")
def create_club() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="yellow", render_order=1),
        "Description": item_desc("club"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
    }
