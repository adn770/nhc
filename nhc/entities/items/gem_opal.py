"""Opal gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_opal")
def create_gem_opal() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="bright_cyan", render_order=1),
        "Description": item_desc("gem_opal"),
        "Gem": Gem(value=200),
    }
