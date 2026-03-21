"""Scroll of Lightning Bolt — ranged damage consumable."""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_lightning")
def create_scroll_lightning() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": Description(
            name=t("items.scroll_lightning.name"),
            short=t("items.scroll_lightning.short"),
            long=t("items.scroll_lightning.long"),
        ),
        "Consumable": Consumable(effect="damage_nearest", dice="3d6", slots=1),
    }
