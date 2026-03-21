"""Skeleton — undead warrior."""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_creature("skeleton")
def create_skeleton() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=1, constitution=2,
                       intelligence=0, wisdom=0, charisma=0),
        "Health": Health(current=6, maximum=6),
        "Renderable": Renderable(glyph="s", color="white", render_order=2),
        "AI": AI(behavior="guard", morale=12, faction="undead"),
        "LootTable": LootTable(entries=[("gold", 0.5, "1d6"),
                                        ("short_sword", 0.2)]),
        "Description": Description(
            name="Skeleton",
            short="a rattling skeleton",
            long="Bleached bones held together by dark magic, "
                 "wielding a notched blade.",
        ),
    }
