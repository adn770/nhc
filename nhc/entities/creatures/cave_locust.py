"""Giant Cave Locust — leaping insect that spits. (BEB: Llagosta de cova)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("cave_locust")
def create_cave_locust() -> dict:
    return {
        "Renderable": Renderable(glyph="L", color="green", render_order=2),
        "Description": creature_desc("cave_locust"),
        "Stats": Stats(strength=1, dexterity=3, constitution=1),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d4"),
        "AI": AI(behavior="aggressive_melee", morale=5, faction="beast"),
    }
