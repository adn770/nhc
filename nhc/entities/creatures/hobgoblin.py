"""Hobgoblin — disciplined goblinoid soldier. (BEB: Hobgoblin)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("hobgoblin")
def create_hobgoblin() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=3, constitution=1),
        "Health": Health(current=5, maximum=5),
        "Renderable": Renderable(glyph="h", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="goblinoid"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[("gold", 0.6, "1d8"), ("short_sword", 0.2)]),
        "Description": Description(
            name=t("creature.hobgoblin.name"),
            short=t("creature.hobgoblin.short"),
            long=t("creature.hobgoblin.long"),
        ),
    }
