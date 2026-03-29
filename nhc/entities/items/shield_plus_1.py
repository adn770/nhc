"""Magic Shield +1 — enchanted shield."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("shield_plus_1")
def create_shield_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_cyan", render_order=1),
        "Description": item_desc("shield_plus_1"),
        "Armor": Armor(slot="shield", defense=1, slots=1, magic_bonus=1),
    }
