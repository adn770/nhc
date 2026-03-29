"""Magic Sling +1 — enchanted sling."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("sling_plus_1")
def create_sling_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("sling_plus_1"),
        "Weapon": Weapon(damage="1d4", type="ranged", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
