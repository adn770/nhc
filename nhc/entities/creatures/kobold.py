"""Kobold — tiny, cunning trap-builder. (BEB: Kobold)"""

from nhc.entities.components import AI, Description, Health, LootTable, Renderable, Stats
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("kobold")
def create_kobold() -> dict:
    return {
        "Stats": Stats(strength=-1, dexterity=2, constitution=0),
        "Health": Health(current=2, maximum=2),
        "Renderable": Renderable(glyph="k", color="yellow", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=6, faction="goblinoid"),
        "LootTable": LootTable(entries=[("gold", 0.5, "1d4")]),
        "Description": Description(
            name=t("creature.kobold.name"),
            short=t("creature.kobold.short"),
            long=t("creature.kobold.long"),
        ),
    }
