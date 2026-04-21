"""Pickpocket — town NPC that looks like a villager and lifts coin."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats, Thief,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("pickpocket")
def create_pickpocket() -> dict:
    return {
        # Identical glyph/color to `villager` — the entire point is
        # that the player cannot tell them apart at a glance.
        "Renderable": Renderable(
            glyph="@", color="white", render_order=2,
        ),
        "Description": creature_desc("pickpocket"),
        "Stats": Stats(
            strength=1, dexterity=3, constitution=1,
            intelligence=2, wisdom=1, charisma=2,
        ),
        "Health": Health(current=5, maximum=5),
        "AI": AI(behavior="thief", morale=5, faction="human"),
        "Errand": Errand(),
        "Thief": Thief(),
    }
