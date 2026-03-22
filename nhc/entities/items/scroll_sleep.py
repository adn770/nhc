"""Scroll of Sleep — induces magical slumber. (BEB: Dormir)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_sleep")
def create_scroll_sleep() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_blue",
                                 render_order=1),
        "Description": Description(
            name=t("items.scroll_sleep.name"),
            short=t("items.scroll_sleep.short"),
            long=t("items.scroll_sleep.long"),
        ),
        # dice = max HD of targets that can be affected (2d8 total HD)
        "Consumable": Consumable(effect="sleep", dice="2d8", slots=1),
    }
