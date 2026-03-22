"""Yellow Mold — releases deadly spore cloud when disturbed. (BEB: Fong groc)"""

from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("yellow_mold")
def create_yellow_mold() -> dict:
    return {
        "Renderable": Renderable(glyph="m", color="bright_yellow",
                                 render_order=2),
        "Description": creature_desc("yellow_mold"),
        "Stats": Stats(strength=0, dexterity=-3, constitution=3),
        "Health": Health(current=9, maximum=9),
        "AI": AI(behavior="idle", morale=12, faction="plant"),
    }
