"""Orc — tough melee fighter."""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_creature("orc")
def create_orc() -> dict:
    return {
        "Stats": Stats(strength=3, dexterity=1, constitution=3,
                       intelligence=0, wisdom=0, charisma=-1),
        "Health": Health(current=10, maximum=10),
        "Renderable": Renderable(glyph="o", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="goblinoid"),
        "LootTable": LootTable(entries=[("gold", 0.7, "3d6"),
                                        ("short_sword", 0.4)]),
        "Description": Description(
            name="Orc",
            short="a hulking orc",
            long="A muscular brute with tusks and crude iron armor. "
                 "It grunts aggressively.",
        ),
    }
