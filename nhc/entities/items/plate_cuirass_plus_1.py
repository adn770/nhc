"""Magic Plate Cuirass +1 — enchanted body armor."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("plate_cuirass_plus_1")
def create_plate_cuirass_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_cyan", render_order=1),
        "Description": item_desc("plate_cuirass_plus_1"),
        "Armor": Armor(slot="body", defense=15, slots=3, magic_bonus=1),
    }
