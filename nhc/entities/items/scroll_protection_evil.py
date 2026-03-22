"""Scroll of Protection from Evil — +1 saves, -1 enemy attacks. (BEB: Protecció del mal)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_protection_evil")
def create_scroll_protection_evil() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_blue", render_order=1),
        "Description": Description(
            name=t("items.scroll_protection_evil.name"),
            short=t("items.scroll_protection_evil.short"),
            long=t("items.scroll_protection_evil.long"),
        ),
        # dice = duration in turns
        "Consumable": Consumable(effect="protection_evil", dice="12", slots=1),
    }
