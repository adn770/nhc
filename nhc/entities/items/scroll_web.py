"""Scroll of Web — entangles all visible creatures. (BEB: Teranyina)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_web")
def create_scroll_web() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="white", render_order=1),
        "Description": Description(
            name=t("items.scroll_web.name"),
            short=t("items.scroll_web.short"),
            long=t("items.scroll_web.long"),
        ),
        # dice = duration in turns; all visible creatures are webbed
        "Consumable": Consumable(effect="web", dice="1d4+1", slots=1),
    }
