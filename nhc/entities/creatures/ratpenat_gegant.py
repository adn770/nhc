"""Ratpenat Gegant (Giant Bat) — large carnivorous bat. (BEB: Ratpenat gegant)"""

from nhc.entities.components import AI, Description, Health, LootTable, Renderable, Stats
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("ratpenat_gegant")
def create_ratpenat_gegant() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=3, constitution=0),
        "Health": Health(current=9, maximum=9),
        "Renderable": Renderable(glyph="v", color="bright_black", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=8, faction="beast"),
        "LootTable": LootTable(entries=[]),
        "Description": Description(
            name=t("creature.ratpenat_gegant.name"),
            short=t("creature.ratpenat_gegant.short"),
            long=t("creature.ratpenat_gegant.long"),
        ),
    }
