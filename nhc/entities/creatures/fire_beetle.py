"""Escarabat de Foc (Giant Fire Beetle) — bioluminescent insect. (BEB: Escarabat de foc)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("fire_beetle")
def create_fire_beetle() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=5, constitution=1),
        "Health": Health(current=6, maximum=6),
        "Renderable": Renderable(glyph="a", color="bright_red", render_order=2),
        "AI": AI(behavior="guard", morale=7, faction="beast"),
        # Defends with powerful mandibles (2d4)
        "Weapon": Weapon(damage="2d4"),
        "LootTable": LootTable(entries=[]),
        "Description": creature_desc("fire_beetle"),
    }
