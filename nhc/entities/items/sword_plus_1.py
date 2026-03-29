"""Magic Sword +1 — enchanted blade."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("sword_plus_1")
def create_sword_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("sword_plus_1"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
