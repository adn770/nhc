"""Bandoler (Bandit) — human outlaw. (BEB: Bandoler)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("bandoler")
def create_bandoler() -> dict:
    return {
        "Stats": Stats(strength=0, dexterity=3, constitution=0),
        "Health": Health(current=4, maximum=4),
        "Renderable": Renderable(glyph="@", color="bright_yellow", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=6, faction="human"),
        "Weapon": Weapon(damage="1d6"),
        "LootTable": LootTable(entries=[("gold", 0.9, "2d6"),
                                        ("dagger", 0.3),
                                        ("short_sword", 0.1)]),
        "Description": Description(
            name=t("creature.bandoler.name"),
            short=t("creature.bandoler.short"),
            long=t("creature.bandoler.long"),
        ),
    }
