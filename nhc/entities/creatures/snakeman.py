"""Home Serp (Snakeman) — serpentine humanoid warrior. (BEB: Home Serp)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("snakeman")
def create_snakeman() -> dict:
    return {
        "Renderable": Renderable(glyph="n", color="green", render_order=2),
        "Description": creature_desc("snakeman"),
        "Stats": Stats(strength=2, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
    }
