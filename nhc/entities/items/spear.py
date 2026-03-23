"""Item — spear."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("spear")
def create_spear() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="white", render_order=1),
        "Description": item_desc("spear"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=2),
    }
