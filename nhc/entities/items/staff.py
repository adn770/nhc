"""Quarterstaff — simple two-handed weapon."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("staff")
def create_staff() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="yellow", render_order=1),
        "Description": item_desc("staff"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=2),
    }
