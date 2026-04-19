"""Cult Leader — ranking cultist. (BEB-style: CultLeader)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("cult_leader")
def create_cult_leader() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=3, constitution=2),
        "Health": Health(current=14, maximum=14),
        "Renderable": Renderable(
            glyph="C", color="bright_magenta", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=9,
                 faction="cultist"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[("gold", 0.9, "3d6"),
                                        ("scroll_bless", 0.4),
                                        ("scroll_cure_wounds", 0.2)]),
        "Description": creature_desc("cult_leader"),
    }
