"""Goblin — weak, aggressive humanoid."""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("goblin")
def create_goblin() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=2, constitution=1,
                       intelligence=0, wisdom=0, charisma=-1),
        "Health": Health(current=4, maximum=4),
        "Renderable": Renderable(glyph="g", color="green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="goblinoid"),
        "LootTable": LootTable(entries=[("gold", 0.8, "2d6"),
                                        ("dagger", 0.3)]),
        "Description": Description(
            name=t("creature.goblin.name"),
            short=t("creature.goblin.short"),
            long=t("creature.goblin.long"),
        ),
    }
