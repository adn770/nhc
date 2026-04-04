"""Crate — container with mixed food and utility loot."""

from nhc.entities.components import (
    BlocksMovement, LootTable, Renderable,
)
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_feature("crate")
def create_crate() -> dict:
    return {
        "Renderable": Renderable(glyph="#", color="yellow",
                                 render_order=1),
        "Description": item_desc("crate"),
        "LootTable": LootTable(entries=[
            ("bread", 0.4),
            ("dried_meat", 0.3),
            ("mushroom", 0.3),
            ("cheese", 0.3),
            ("healing_potion", 0.2),
            ("torch", 0.2),
        ]),
        "BlocksMovement": BlocksMovement(),
        "Chest": True,
    }
