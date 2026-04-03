"""Item — pickaxe."""

from nhc.entities.components import DiggingTool, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("pickaxe")
def create_pickaxe() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_cyan", render_order=1),
        "Description": item_desc("pickaxe"),
        "Weapon": Weapon(damage="1d6", type="melee", slots=2),
        "DiggingTool": DiggingTool(bonus=3),
    }
