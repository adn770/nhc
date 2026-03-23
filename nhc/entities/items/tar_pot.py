"""Item — tar pot."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("tar_pot")
def create_tar_pot() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_black", render_order=1),
        "Description": item_desc("tar_pot"),
    }
