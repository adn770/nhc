"""Desencantador (Disenchanter) — destroys magic items on touch. (BEB: Desencantador)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    DisenchantTouch,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("disenchanter")
def create_disenchanter() -> dict:
    return {
        "Renderable": Renderable(glyph="d", color="magenta", render_order=2),
        "Description": creature_desc("disenchanter"),
        "Stats": Stats(strength=2, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d4"),
        "DisenchantTouch": DisenchantTouch(),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
    }
