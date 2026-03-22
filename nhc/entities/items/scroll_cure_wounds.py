"""Scroll of Cure Wounds — heals 1d6+1 HP. (BEB: Curar ferides lleus)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_cure_wounds")
def create_scroll_cure_wounds() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="green", render_order=1),
        "Description": Description(
            name=t("items.scroll_cure_wounds.name"),
            short=t("items.scroll_cure_wounds.short"),
            long=t("items.scroll_cure_wounds.long"),
        ),
        "Consumable": Consumable(effect="heal", dice="1d6+1", slots=1),
    }
