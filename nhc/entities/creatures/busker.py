"""Busker — plays for coin at a busy corner."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("busker")
def create_busker() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_cyan", render_order=2,
        ),
        "Description": creature_desc("busker"),
        "Stats": Stats(
            strength=0, dexterity=2, constitution=1,
            intelligence=1, wisdom=1, charisma=2,
        ),
        "Health": Health(current=5, maximum=5),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "Errand": Errand(),
    }
