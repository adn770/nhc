"""Chest — contains loot, opened by the player."""

from nhc.entities.components import (
    BlocksMovement, LootTable, Renderable,
)
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_feature("chest")
def create_chest() -> dict:
    return {
        "Renderable": Renderable(glyph="=", color="bright_yellow", render_order=1),
        "Description": item_desc("chest"),
        "LootTable": LootTable(entries=[
            ("healing_potion", 0.5),
            ("gold", 0.8, "3d6"),
        ]),
        "BlocksMovement": BlocksMovement(),
        "Chest": True,
    }
