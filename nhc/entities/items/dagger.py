"""Dagger — light melee weapon."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("dagger")
def create_dagger() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="white", render_order=1),
        "Description": Description(
            name=t("items.dagger.name"),
            short=t("items.dagger.short"),
            long=t("items.dagger.long"),
        ),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
    }
