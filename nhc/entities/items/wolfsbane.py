"""Wolfsbane — repels lycanthropes."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("wolfsbane")
def create_wolfsbane() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="magenta", render_order=1),
        "Description": item_desc("wolfsbane"),
    }
