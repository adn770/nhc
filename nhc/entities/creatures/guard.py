"""Guard — keep courtyard sentry."""

from nhc.entities.components import (
    AI, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("guard")
def create_guard() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=9, maximum=9),
        "Renderable": Renderable(
            glyph="g", color="bright_blue", render_order=2,
        ),
        "AI": AI(behavior="aggressive_melee", morale=8,
                 faction="guardhouse"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[
            ("gold", 0.7, "1d8"),
            ("short_sword", 0.25),
            ("shield", 0.15),
        ]),
        "Description": creature_desc("guard"),
    }
