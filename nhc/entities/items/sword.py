"""Sword — standard melee weapon."""

from nhc.entities.components import Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("sword")
def create_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="cyan", render_order=1),
        "Description": item_desc("sword"),
        "Weapon": Weapon(damage="1d8", type="melee", slots=1),
    }
