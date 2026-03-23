"""Arrows — ammunition for bows and crossbows."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("arrows")
def create_arrows() -> dict:
    return {
        "Renderable": Renderable(glyph="/", color="yellow", render_order=1),
        "Description": item_desc("arrows"),
    }
