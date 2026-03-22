"""Dragon Lizard — fire-breathing reptile. (BEB: Llangardaix drac)"""

from nhc.entities.components import (
    AI, FrostBreath, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("dragon_lizard")
def create_dragon_lizard() -> dict:
    return {
        "Renderable": Renderable(glyph="D", color="bright_red",
                                 render_order=2),
        "Description": creature_desc("dragon_lizard"),
        "Stats": Stats(strength=3, dexterity=2, constitution=3),
        "Health": Health(current=22, maximum=22),
        "Weapon": Weapon(damage="1d8"),
        "FrostBreath": FrostBreath(dice="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="beast"),
        "LootTable": LootTable(entries=[("gold", 0.6, "4d6")]),
    }
