"""Diamond gem — most valuable gemstone."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_diamond")
def create_gem_diamond() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="bright_white", render_order=1),
        "Description": item_desc("gem_diamond"),
        "Gem": Gem(value=500),
    }
