"""Hand Axe — light throwable axe."""

from nhc.entities.components import Throwable, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("hand_axe")
def create_hand_axe() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="white", render_order=1),
        "Description": item_desc("hand_axe"),
        "Weapon": Weapon(damage="1d6", type="melee", slots=1),
        "Throwable": Throwable(),
    }
