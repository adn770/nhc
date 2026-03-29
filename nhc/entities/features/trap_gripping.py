"""Gripping Trap — iron jaws that wound and immobilize."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_gripping")
def create_gripping_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_yellow", render_order=0),
        "Description": Description(
            name=t("features.trap_gripping.name"),
            short=t("features.trap_gripping.short"),
            long=t("features.trap_gripping.long"),
        ),
        "Trap": Trap(damage="1d4", dc=12, hidden=True, effect="gripping"),
    }
