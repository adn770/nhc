"""Ochre Jelly — splits when hit, acid damage. (BEB: Gelatina ocre)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("ochre_jelly")
def create_ochre_jelly() -> dict:
    return {
        "Renderable": Renderable(glyph="j", color="yellow", render_order=2),
        "Description": creature_desc("ochre_jelly"),
        "Stats": Stats(strength=2, dexterity=-1, constitution=3),
        "Health": Health(current=20, maximum=20),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="ooze"),
    }
