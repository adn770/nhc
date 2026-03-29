"""Magic Axe +1 — enchanted axe."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("axe_plus_1")
def create_axe_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("axe_plus_1"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
