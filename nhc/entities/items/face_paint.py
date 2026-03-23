"""Item — face paint."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("face_paint")
def create_face_paint() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_red", render_order=1),
        "Description": item_desc("face_paint"),
    }
