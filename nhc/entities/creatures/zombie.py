"""Zombie — slow, durable undead."""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("zombie")
def create_zombie() -> dict:
    return {
        "Stats": Stats(strength=2, dexterity=0, constitution=4,
                       intelligence=-1, wisdom=0, charisma=-2),
        "Health": Health(current=12, maximum=12),
        "Renderable": Renderable(glyph="Z", color="bright_green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=12, faction="undead"),
        "LootTable": LootTable(entries=[("gold", 0.3, "1d6")]),
        "Description": Description(
            name=t("creature.zombie.name"),
            short=t("creature.zombie.short"),
            long=t("creature.zombie.long"),
        ),
    }
