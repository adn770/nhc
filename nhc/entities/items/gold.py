"""Gold coins — currency."""

from nhc.entities.components import Description, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("gold")
def create_gold() -> dict:
    return {
        "Renderable": Renderable(glyph="$", color="bright_yellow", render_order=1),
        "Description": Description(
            name=t("items.gold.name"),
            short=t("items.gold.short"),
            long=t("items.gold.long"),
        ),
        "Gold": True,  # Tag component
    }
