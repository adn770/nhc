"""Gnoll Chieftain — gnoll warband leader."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("gnoll_chieftain")
def create_gnoll_chieftain() -> dict:
    return {
        "Stats": Stats(strength=3, dexterity=3, constitution=3),
        "Health": Health(current=16, maximum=16),
        "Renderable": Renderable(
            glyph="G", color="bright_yellow", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=11,
                 faction="gnoll"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[("gold", 0.8, "3d6"),
                                        ("axe", 0.3),
                                        ("bow", 0.2)]),
        "Description": creature_desc("gnoll_chieftain"),
    }
