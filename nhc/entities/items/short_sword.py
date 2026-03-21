"""Short Sword — light melee weapon."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("short_sword")
def create_short_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": Description(
            name=t("items.short_sword.name"),
            short=t("items.short_sword.short"),
            long=t("items.short_sword.long"),
        ),
        "Weapon": Weapon(damage="1d6", type="melee", slots=1),
    }
