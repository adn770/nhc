"""Sword — standard melee weapon."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("sword")
def create_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="cyan", render_order=1),
        "Description": Description(
            name=t("items.sword.name"),
            short=t("items.sword.short"),
            long=t("items.sword.long"),
        ),
        "Weapon": Weapon(damage="1d8", type="melee", slots=1),
    }
