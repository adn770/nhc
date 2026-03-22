"""Gray Ooze — acid ooze that dissolves metal. (BEB: Llot gris)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("gray_ooze")
def create_gray_ooze() -> dict:
    return {
        "Renderable": Renderable(glyph="o", color="grey", render_order=2),
        "Description": creature_desc("gray_ooze"),
        "Stats": Stats(strength=2, dexterity=-2, constitution=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="ooze"),
    }
