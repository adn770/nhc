"""Cridaner (Shrieker) — stationary fungus that screams to alert creatures. (BEB: Cridaner)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("shrieker")
def create_shrieker() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="magenta", render_order=2),
        "Description": creature_desc("shrieker"),
        "Stats": Stats(strength=0, dexterity=0),
        "Health": Health(current=14, maximum=14),
        "AI": AI(behavior="shrieker", morale=12),
        "BlocksMovement": BlocksMovement(),
    }
