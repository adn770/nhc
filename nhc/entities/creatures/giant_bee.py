"""Giant Bee — poisonous stinging insect. (BEB: Abella Gegant)"""

from nhc.entities.components import (
    AI, Description, Health, LootTable, Poison, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("giant_bee")
def create_giant_bee() -> dict:
    return {
        "Stats": Stats(strength=0, dexterity=3, constitution=0),
        "Health": Health(current=1, maximum=1),
        "Renderable": Renderable(glyph="B", color="bright_yellow",
                                 render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=9, faction="vermin"),
        "LootTable": LootTable(entries=[]),
        # Poison tag signals to combat: on hit, inflict Poison
        "VenomousStrike": True,
        "Description": Description(
            name=t("creature.giant_bee.name"),
            short=t("creature.giant_bee.short"),
            long=t("creature.giant_bee.long"),
        ),
    }
