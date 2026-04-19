"""Quartermaster — keep gate warden in charge of stores."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("quartermaster")
def create_quartermaster() -> dict:
    return {
        "Stats": Stats(
            strength=2, dexterity=2, constitution=2,
            intelligence=2, wisdom=2, charisma=2,
        ),
        "Health": Health(current=12, maximum=12),
        "Renderable": Renderable(
            glyph="q", color="yellow", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=9,
                 faction="guardhouse"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[
            ("gold", 0.9, "2d8"),
            ("rations", 0.4),
            ("lantern", 0.2),
        ]),
        "Description": creature_desc("quartermaster"),
    }
