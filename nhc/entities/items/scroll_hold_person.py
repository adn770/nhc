"""Scroll of Hold Person — paralyzes humanoids. (BEB: Retenir persona)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_hold_person")
def create_scroll_hold_person() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="yellow", render_order=1),
        "Description": Description(
            name=t("items.scroll_hold_person.name"),
            short=t("items.scroll_hold_person.short"),
            long=t("items.scroll_hold_person.long"),
        ),
        # dice = duration in turns; targets 1d4 visible humanoids
        "Consumable": Consumable(effect="hold_person", dice="9", slots=1),
    }
