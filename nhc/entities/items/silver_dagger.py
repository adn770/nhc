"""Silver Dagger — effective against lycanthropes and undead."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("silver_dagger")
def create_silver_dagger() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": item_desc("silver_dagger"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
        "Enchanted": Enchanted(),
    }
