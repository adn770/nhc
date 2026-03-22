"""Giant Frog — amphibious predator with sticky tongue. (BEB: Granota gegant)"""

from nhc.entities.components import (
    AI, Health, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_frog")
def create_giant_frog() -> dict:
    return {
        "Renderable": Renderable(glyph="F", color="green", render_order=2),
        "Description": creature_desc("giant_frog"),
        "Stats": Stats(strength=2, dexterity=1, constitution=2),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=6, faction="beast"),
    }
