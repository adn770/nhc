"""Scroll of Mirror Image — creates 1d4 illusions that absorb hits. (BEB: Imatge mirall)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_mirror_image")
def create_scroll_mirror_image() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="cyan", render_order=1),
        "Description": Description(
            name=t("items.scroll_mirror_image.name"),
            short=t("items.scroll_mirror_image.short"),
            long=t("items.scroll_mirror_image.long"),
        ),
        # dice = number of images created (1d4)
        "Consumable": Consumable(effect="mirror_image", dice="1d4", slots=1),
    }
