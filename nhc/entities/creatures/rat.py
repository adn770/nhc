"""Giant Rat — weak, fast vermin."""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("rat")
def create_rat() -> dict:
    return {
        "Stats": Stats(strength=0, dexterity=3, constitution=0),
        "Health": Health(current=2, maximum=2),
        "Renderable": Renderable(glyph="r", color="bright_red", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=4, faction="vermin"),
        "LootTable": LootTable(entries=[]),
        "Description": Description(
            name=t("creature.rat.name"),
            short=t("creature.rat.short"),
            long=t("creature.rat.long"),
        ),
    }
