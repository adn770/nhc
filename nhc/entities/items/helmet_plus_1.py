"""Magic Helmet +1 — enchanted helmet."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("helmet_plus_1")
def create_helmet_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_cyan", render_order=1),
        "Description": item_desc("helmet_plus_1"),
        "Armor": Armor(slot="helmet", defense=1, slots=1, magic_bonus=1),
    }
