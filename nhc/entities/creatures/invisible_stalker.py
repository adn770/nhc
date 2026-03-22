"""Invisible Stalker — permanently invisible air elemental. (BEB: Assetjador invisible)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("invisible_stalker")
def create_invisible_stalker() -> dict:
    return {
        "Renderable": Renderable(glyph="I", color="bright_cyan",
                                 render_order=2),
        "Description": creature_desc("invisible_stalker"),
        "Stats": Stats(strength=3, dexterity=5, constitution=3),
        "Health": Health(current=32, maximum=32),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="elemental"),
        "PermanentInvisible": True,
    }
