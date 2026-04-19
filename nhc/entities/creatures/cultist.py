"""Cultist — robed caster-flavoured humanoid. (BEB-style: Cultist)"""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("cultist")
def create_cultist() -> dict:
    return {
        "Stats": Stats(strength=0, dexterity=2, constitution=1),
        "Health": Health(current=5, maximum=5),
        "Renderable": Renderable(glyph="c", color="magenta", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="cultist"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[("gold", 0.7, "1d8"),
                                        ("dagger", 0.3),
                                        ("scroll_bless", 0.1)]),
        "Description": creature_desc("cultist"),
    }
