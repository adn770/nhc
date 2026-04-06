"""Amethyst gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_amethyst")
def create_gem_amethyst() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="magenta", render_order=1),
        "Description": item_desc("gem_amethyst"),
        "Gem": Gem(value=150),
    }
