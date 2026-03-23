"""Leather Armor — light protection."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("leather_armor")
def create_leather_armor() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="yellow", render_order=1),
        "Description": item_desc("leather_armor"),
        "Armor": Armor(slot="body", defense=11, slots=1),
    }
