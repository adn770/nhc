"""Market vendor — stallholder hawking wares on the plaza."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("market_vendor")
def create_market_vendor() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_green", render_order=2,
        ),
        "Description": creature_desc("market_vendor"),
        "Stats": Stats(
            strength=0, dexterity=1, constitution=1,
            intelligence=1, wisdom=1, charisma=2,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=4, faction="human"),
        "Errand": Errand(),
    }
