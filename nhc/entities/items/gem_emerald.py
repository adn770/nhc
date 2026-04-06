"""Emerald gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_emerald")
def create_gem_emerald() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="bright_green", render_order=1),
        "Description": item_desc("gem_emerald"),
        "Gem": Gem(value=250),
    }
