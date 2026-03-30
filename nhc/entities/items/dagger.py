"""Dagger — light melee weapon."""

from nhc.entities.components import Throwable, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("dagger")
def create_dagger() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="white", render_order=1),
        "Description": item_desc("dagger"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
        "Throwable": Throwable(),
    }
