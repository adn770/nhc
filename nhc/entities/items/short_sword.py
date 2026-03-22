"""Short Sword — light melee weapon."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("short_sword")
def create_short_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": item_desc("short_sword"),
        "Weapon": Weapon(damage="1d6", type="melee", slots=1),
    }
