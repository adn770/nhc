"""Magic Leather Armor +1 — enchanted body armor."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("leather_armor_plus_1")
def create_leather_armor_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_cyan", render_order=1),
        "Description": item_desc("leather_armor_plus_1"),
        "Armor": Armor(slot="body", defense=11, slots=1, magic_bonus=1),
    }
