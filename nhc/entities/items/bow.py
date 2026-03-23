"""Item — bow."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("bow")
def create_bow() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="yellow", render_order=1),
        "Description": item_desc("bow"),
        "Weapon": Weapon(damage="1d6", type="ranged", slots=2),
    }
