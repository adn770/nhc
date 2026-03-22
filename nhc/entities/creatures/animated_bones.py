"""Animated Bones — weak undead, crumbling remains. (BEB: Ossos)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Undead
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("animated_bones")
def create_animated_bones() -> dict:
    return {
        "Renderable": Renderable(glyph="s", color="white", render_order=2),
        "Description": creature_desc("animated_bones"),
        "Stats": Stats(strength=0, dexterity=0, constitution=0),
        "Health": Health(current=3, maximum=3),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="undead"),
        "Undead": Undead(),
    }
