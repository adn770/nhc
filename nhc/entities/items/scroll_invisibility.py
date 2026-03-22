"""Scroll of Invisibility — caster becomes invisible. (BEB: Invisibilitat)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_invisibility")
def create_scroll_invisibility() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_black", render_order=1),
        "Description": Description(
            name=t("items.scroll_invisibility.name"),
            short=t("items.scroll_invisibility.short"),
            long=t("items.scroll_invisibility.long"),
        ),
        # dice = duration in turns; breaks when player attacks
        "Consumable": Consumable(effect="invisibility", dice="6", slots=1),
    }
