"""Barrel — container with food-heavy loot."""

from nhc.entities.components import (
    BlocksMovement, LootTable, Renderable,
)
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_feature("barrel")
def create_barrel() -> dict:
    return {
        "Renderable": Renderable(glyph="0", color="yellow",
                                 render_order=1),
        "Description": item_desc("barrel"),
        "LootTable": LootTable(entries=[
            ("rations", 0.5),
            ("bread", 0.4),
            ("dried_meat", 0.4),
            ("apple", 0.3),
            ("cheese", 0.3),
        ]),
        "BlocksMovement": BlocksMovement(),
        "Chest": True,
    }
