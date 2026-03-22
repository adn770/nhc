"""Ocell Mal Averany (Bird of Ill Omen) — predatory giant raven. (BEB: Ocell mal averany)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("ocell_mal_averany")
def create_ocell_mal_averany() -> dict:
    return {
        "Renderable": Renderable(glyph="b", color="dark_grey", render_order=2),
        "Description": creature_desc("ocell_mal_averany"),
        "Stats": Stats(strength=2, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d4"),
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
    }
