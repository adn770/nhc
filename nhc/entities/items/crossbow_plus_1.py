"""Magic Crossbow +1 — enchanted crossbow."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("crossbow_plus_1")
def create_crossbow_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("crossbow_plus_1"),
        "Weapon": Weapon(damage="1d8", type="ranged", slots=2, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
