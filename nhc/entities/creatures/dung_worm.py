"""Dung Worm — tunneling creature found in refuse. (BEB: Cuc femer)"""

from nhc.entities.components import AI, Health, Renderable, Stats, Weapon
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("dung_worm")
def create_dung_worm() -> dict:
    return {
        "Renderable": Renderable(glyph="w", color="yellow", render_order=2),
        "Description": creature_desc("dung_worm"),
        "Stats": Stats(strength=2, dexterity=0, constitution=2),
        "Health": Health(current=12, maximum=12),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="beast"),
    }
