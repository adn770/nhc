"""Magic Hand Axe +1 — enchanted hand axe."""

from nhc.entities.components import Throwable, Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("hand_axe_plus_1")
def create_hand_axe_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("hand_axe_plus_1"),
        "Weapon": Weapon(damage="1d6", type="melee", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
        "Throwable": Throwable(),
    }
