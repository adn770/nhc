"""Topaz gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_topaz")
def create_gem_topaz() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="bright_yellow", render_order=1),
        "Description": item_desc("gem_topaz"),
        "Gem": Gem(value=100),
    }
