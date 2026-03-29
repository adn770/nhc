"""Magic Spear +1 — enchanted spear."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("spear_plus_1")
def create_spear_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("spear_plus_1"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
