"""Item — pick."""

from nhc.entities.components import DiggingTool, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("pick")
def create_pick() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("pick"),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
        "DiggingTool": DiggingTool(bonus=0),
    }
