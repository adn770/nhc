"""Carnivorous Flower — grapples and digests prey. (BEB: Flor carnívora)"""

from nhc.entities.components import (
    AI, Health, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("carnivorous_flower")
def create_carnivorous_flower() -> dict:
    return {
        "Renderable": Renderable(glyph="f", color="bright_red",
                                 render_order=2),
        "Description": creature_desc("carnivorous_flower"),
        "Stats": Stats(strength=3, dexterity=-1, constitution=3),
        "Health": Health(current=18, maximum=18),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="guard", morale=12, faction="plant"),
    }
