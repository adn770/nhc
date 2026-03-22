"""Mechanical Raven — clockwork construct, messenger. (BEB: Corb mecànic)"""

from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("mechanical_raven")
def create_mechanical_raven() -> dict:
    return {
        "Renderable": Renderable(glyph="c", color="cyan", render_order=2),
        "Description": creature_desc("mechanical_raven"),
        "Stats": Stats(strength=0, dexterity=4, constitution=1),
        "Health": Health(current=5, maximum=5),
        "AI": AI(behavior="idle", morale=12, faction="construct"),
    }
