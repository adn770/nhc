"""Poison Trap — poison darts on trigger."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_poison")
def create_poison_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_green", render_order=0),
        "Description": Description(
            name=t("features.trap_poison.name"),
            short=t("features.trap_poison.short"),
            long=t("features.trap_poison.long"),
        ),
        "Trap": Trap(damage="1d4", dc=12, hidden=True, effect="poison"),
    }
