"""Javelin — light throwing spear."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("javelin")
def create_javelin() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="yellow", render_order=1),
        "Description": item_desc("javelin"),
        "Weapon": Weapon(damage="1d4", type="ranged", slots=1),
    }
