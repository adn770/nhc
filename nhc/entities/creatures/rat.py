"""Rat — tiny vermin, nuisance in swarms. (BEB: Rata)"""

from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("rat")
def create_rat() -> dict:
    return {
        "Renderable": Renderable(glyph="r", color="grey", render_order=2),
        "Description": creature_desc("rat"),
        "Stats": Stats(strength=-1, dexterity=2, constitution=-1),
        "Health": Health(current=1, maximum=1),
        "AI": AI(behavior="aggressive_melee", morale=5, faction="beast"),
    }
