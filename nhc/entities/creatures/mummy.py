"""Mummy — undead horror with rotting curse and fear aura. (BEB: Mòmia)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    FearAura,
    Health,
    MummyRot,
    Renderable,
    Stats,
    Undead,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("mummy")
def create_mummy() -> dict:
    return {
        "Renderable": Renderable(glyph="M", color="yellow", render_order=2),
        "Description": creature_desc("mummy"),
        "Stats": Stats(strength=4, dexterity=1),
        "Health": Health(current=25, maximum=25),
        "Weapon": Weapon(damage="1d8"),
        "MummyRot": MummyRot(),
        "FearAura": FearAura(radius=3, save_dc=12),
        "AI": AI(behavior="aggressive_melee", morale=12),
        "BlocksMovement": BlocksMovement(),
        "Undead": Undead(),
    }
