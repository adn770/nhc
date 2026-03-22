"""Bat — small flying creature, echolocation. (BEB: Ratpenat)"""

from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("bat")
def create_bat() -> dict:
    return {
        "Renderable": Renderable(glyph="b", color="grey", render_order=2),
        "Description": creature_desc("bat"),
        "Stats": Stats(strength=-1, dexterity=3, constitution=-1),
        "Health": Health(current=1, maximum=1),
        "AI": AI(behavior="aggressive_melee", morale=4, faction="beast"),
    }
