"""Scroll of Charm Person — makes a humanoid fight for you. (BEB: Encisar persona)"""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("scroll_charm_person")
def create_scroll_charm_person() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": Description(
            name=t("items.scroll_charm_person.name"),
            short=t("items.scroll_charm_person.short"),
            long=t("items.scroll_charm_person.long"),
        ),
        # dice = duration in turns; targets nearest visible humanoid
        "Consumable": Consumable(effect="charm_person", dice="9", slots=1),
    }
