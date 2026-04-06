"""Ruby gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_ruby")
def create_gem_ruby() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="bright_red", render_order=1),
        "Description": item_desc("gem_ruby"),
        "Gem": Gem(value=300),
    }
