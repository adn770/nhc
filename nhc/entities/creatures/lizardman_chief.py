"""Lizardman Chief — lizardman warband leader."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("lizardman_chief")
def create_lizardman_chief() -> dict:
    return {
        "Stats": Stats(strength=3, dexterity=4, constitution=3),
        "Health": Health(current=16, maximum=16),
        "Renderable": Renderable(
            glyph="L", color="bright_green", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=12,
                 faction="humanoid"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[("gold", 0.7, "2d8"),
                                        ("spear", 0.3),
                                        ("shield", 0.2)]),
        "Description": creature_desc("lizardman_chief"),
    }
