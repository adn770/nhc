"""Healing Potion — restores hit points."""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("healing_potion")
def create_healing_potion() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="red", render_order=1),
        "Description": Description(
            name=t("items.healing_potion.name"),
            short=t("items.healing_potion.short"),
            long=t("items.healing_potion.long"),
        ),
        "Consumable": Consumable(effect="heal", dice="2d4+2", slots=1),
    }
