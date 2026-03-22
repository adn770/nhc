"""Scroll of Bless — grants +1 to attacks and damage. (BEB: Beneir)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_bless")
def create_scroll_bless() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white", render_order=1),
        "Description": Description(
            name=t("items.scroll_bless.name"),
            short=t("items.scroll_bless.short"),
            long=t("items.scroll_bless.long"),
        ),
        # dice = duration in turns
        "Consumable": Consumable(effect="bless", dice="6", slots=1),
    }
