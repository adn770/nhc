"""Long Sword — heavy two-handed blade."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("long_sword")
def create_long_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": item_desc("long_sword"),
        "Weapon": Weapon(damage="1d10", type="melee", slots=2),
    }
