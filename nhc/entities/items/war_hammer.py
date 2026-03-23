"""Item — war hammer."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("war_hammer")
def create_war_hammer() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("war_hammer"),
        "Weapon": Weapon(damage="1d10", type="melee", slots=3),
    }
