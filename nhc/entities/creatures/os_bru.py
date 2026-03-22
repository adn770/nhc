"""Os Bru (Brown Bear) — large, territorial bear. (BEB: Os bru)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("os_bru")
def create_os_bru() -> dict:
    return {
        # Multi-attack (2×claw 1d4 + bite 1d8); simplified to bite + STR bonus
        "Stats": Stats(strength=4, dexterity=3, constitution=3),
        "Health": Health(current=22, maximum=22),
        "Renderable": Renderable(glyph="c", color="bright_yellow", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="beast"),
        "Weapon": Weapon(damage="1d8"),
        "LootTable": LootTable(entries=[]),
        "Description": Description(
            name=t("creature.os_bru.name"),
            short=t("creature.os_bru.short"),
            long=t("creature.os_bru.long"),
        ),
    }
