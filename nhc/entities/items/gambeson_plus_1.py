"""Magic Gambeson +1 — enchanted body armor."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("gambeson_plus_1")
def create_gambeson_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_cyan", render_order=1),
        "Description": item_desc("gambeson_plus_1"),
        "Armor": Armor(slot="body", defense=12, slots=1, magic_bonus=1),
    }
