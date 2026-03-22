"""Black Pudding — large ooze that splits and dissolves weapons. (BEB: Púding negre)"""

from nhc.entities.components import (
    AI, BlocksMovement, Health, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("black_pudding")
def create_black_pudding() -> dict:
    return {
        "Renderable": Renderable(glyph="P", color="bright_black",
                                 render_order=2),
        "Description": creature_desc("black_pudding"),
        "Stats": Stats(strength=4, dexterity=-2, constitution=4),
        "Health": Health(current=45, maximum=45),
        "Weapon": Weapon(damage="2d6"),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="ooze"),
        "BlocksMovement": BlocksMovement(),
    }
