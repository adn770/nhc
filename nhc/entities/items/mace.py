"""Item — mace."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("mace")
def create_mace() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="cyan", render_order=1),
        "Description": item_desc("mace"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=2),
    }
