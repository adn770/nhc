"""Violet Fungus — rotting touch attacks nearby creatures. (BEB: Bolet violeta)"""

from nhc.entities.components import AI, Health, Poison, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("violet_fungus")
def create_violet_fungus() -> dict:
    return {
        "Renderable": Renderable(glyph="f", color="magenta", render_order=2),
        "Description": creature_desc("violet_fungus"),
        "Stats": Stats(strength=1, dexterity=-2, constitution=2),
        "Health": Health(current=12, maximum=12),
        "AI": AI(behavior="guard", morale=12, faction="plant"),
    }
