"""Garnet gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_garnet")
def create_gem_garnet() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="red", render_order=1),
        "Description": item_desc("gem_garnet"),
        "Gem": Gem(value=80),
    }
