"""Green Slime — dissolves armor and flesh on contact. (BEB: Llim verd)"""

from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("green_slime")
def create_green_slime() -> dict:
    return {
        "Renderable": Renderable(glyph="s", color="bright_green",
                                 render_order=2),
        "Description": creature_desc("green_slime"),
        "Stats": Stats(strength=0, dexterity=-2, constitution=2),
        "Health": Health(current=9, maximum=9),
        "AI": AI(behavior="idle", morale=12, faction="ooze"),
    }
