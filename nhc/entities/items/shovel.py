"""Item — shovel."""

from nhc.entities.components import DiggingTool, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("shovel")
def create_shovel() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("shovel"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
        "DiggingTool": DiggingTool(bonus=-2),
    }
