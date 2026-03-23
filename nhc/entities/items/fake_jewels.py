"""Item — fake jewels."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("fake_jewels")
def create_fake_jewels() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow", render_order=1),
        "Description": item_desc("fake_jewels"),
    }
