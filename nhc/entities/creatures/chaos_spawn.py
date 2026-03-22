"""Desori — chaotic creature of pure entropy. (BEB: Desori)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("chaos_spawn")
def create_chaos_spawn() -> dict:
    return {
        "Renderable": Renderable(glyph="d", color="magenta", render_order=2),
        "Description": creature_desc("chaos_spawn"),
        "Stats": Stats(strength=2, dexterity=3, constitution=2),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="chaos"),
    }
