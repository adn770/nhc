"""Commander — keep's ranking officer."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("commander")
def create_commander() -> dict:
    return {
        "Stats": Stats(
            strength=3, dexterity=3, constitution=3,
            intelligence=2, wisdom=2, charisma=3,
        ),
        "Health": Health(current=18, maximum=18),
        "Renderable": Renderable(
            glyph="C", color="bright_cyan", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=10,
                 faction="guardhouse"),
        "Weapon": Weapon(damage="1d10"),
        "LootTable": LootTable(entries=[
            ("gold", 1.0, "3d8"),
            ("sword", 0.3),
            ("shield", 0.25),
            ("helmet", 0.2),
        ]),
        "Description": creature_desc("commander"),
    }
