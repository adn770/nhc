"""Sapphire gem."""

from nhc.entities.components import Gem, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gem_sapphire")
def create_gem_sapphire() -> dict:
    return {
        "Renderable": Renderable(glyph="*", color="bright_blue", render_order=1),
        "Description": item_desc("gem_sapphire"),
        "Gem": Gem(value=250),
    }
