"""Scroll of Haste — doubles attacks for 3 turns. (BEB: Apressar)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_haste")
def create_scroll_haste() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="yellow", render_order=1),
        "Description": Description(
            name=t("items.scroll_haste.name"),
            short=t("items.scroll_haste.short"),
            long=t("items.scroll_haste.long"),
        ),
        # dice = duration in turns
        "Consumable": Consumable(effect="haste", dice="3", slots=1),
    }
