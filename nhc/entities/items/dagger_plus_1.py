"""Magic Dagger +1 — enchanted dagger."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("dagger_plus_1")
def create_dagger_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("dagger_plus_1"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
