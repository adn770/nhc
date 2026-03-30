"""Healing Bandage — slow heal over time."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("healing_bandage")
def create_healing_bandage() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("healing_bandage"),
        "Consumable": Consumable(effect="heal", dice="1d2", slots=1),
        "Throwable": Throwable(),
    }
