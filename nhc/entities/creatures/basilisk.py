"""Basilisk — 8-legged reptile with petrifying gaze. (BEB: Basilisc)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("basilisk")
def create_basilisk() -> dict:
    return {
        "Stats": Stats(strength=3, dexterity=1, constitution=3),
        "Health": Health(current=28, maximum=28),  # 6+1 HD average
        "Renderable": Renderable(glyph="B", color="green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="beast"),
        "LootTable": LootTable(entries=[("gold", 0.3, "4d6")]),
        # PetrifyingGaze: player entering melee range must save vs. paralysis
        "PetrifyingGaze": True,
        "Description": creature_desc("basilisk"),
    }
