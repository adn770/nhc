"""Giant Lizard — large simple reptile. (BEB: Llangardaix gegant)"""

from nhc.entities.components import (
    AI, Health, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_lizard")
def create_giant_lizard() -> dict:
    return {
        "Renderable": Renderable(glyph="l", color="green", render_order=2),
        "Description": creature_desc("giant_lizard"),
        "Stats": Stats(strength=2, dexterity=1, constitution=2),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="beast"),
    }
