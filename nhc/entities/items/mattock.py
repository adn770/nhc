"""Item — mattock."""

from nhc.entities.components import DiggingTool, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("mattock")
def create_mattock() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_cyan", render_order=1),
        "Description": item_desc("mattock"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=2),
        "DiggingTool": DiggingTool(bonus=5),
    }
