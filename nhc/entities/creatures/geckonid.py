"""Geckonid Lizard — wall-climbing reptile. (BEB: Llangardaix gecònid)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("geckonid")
def create_geckonid() -> dict:
    return {
        "Renderable": Renderable(glyph="l", color="bright_green",
                                 render_order=2),
        "Description": creature_desc("geckonid"),
        "Stats": Stats(strength=1, dexterity=3, constitution=1),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=6, faction="beast"),
    }
