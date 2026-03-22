"""Insect Swarm — area damage, hard to kill with weapons. (BEB: Eixam d'insectes)"""

from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("insect_swarm")
def create_insect_swarm() -> dict:
    return {
        "Renderable": Renderable(glyph="i", color="yellow", render_order=2),
        "Description": creature_desc("insect_swarm"),
        "Stats": Stats(strength=0, dexterity=3, constitution=1),
        "Health": Health(current=9, maximum=9),
        "AI": AI(behavior="aggressive_melee", morale=11, faction="beast"),
    }
