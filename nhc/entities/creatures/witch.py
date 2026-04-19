"""Witch — solitary hostile caster squatting in an abandoned cottage."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("witch")
def create_witch() -> dict:
    return {
        "Stats": Stats(
            strength=0, dexterity=2, constitution=1,
            intelligence=3, wisdom=3, charisma=2,
        ),
        "Health": Health(current=14, maximum=14),
        "Renderable": Renderable(
            glyph="w", color="bright_magenta", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=8,
                 faction="solitary"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[
            ("gold", 0.7, "2d6"),
            ("scroll_sleep", 0.25),
            ("scroll_charm_person", 0.2),
            ("potion_invisibility", 0.1),
        ]),
        "Description": creature_desc("witch"),
    }
