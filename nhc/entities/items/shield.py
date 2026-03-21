"""Shield — defensive equipment."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_item("shield")
def create_shield() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": Description(
            name=t("items.shield.name"),
            short=t("items.shield.short"),
            long=t("items.shield.long"),
        ),
        "Shield": True,  # Tag component for armor bonus
    }
