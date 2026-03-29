"""Magic Halberd +1 — enchanted halberd."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("halberd_plus_1")
def create_halberd_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("halberd_plus_1"),
        "Weapon": Weapon(damage="1d10", type="melee", slots=2, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
