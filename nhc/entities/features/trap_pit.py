"""Pit Trap — hidden hazard."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_pit")
def create_pit_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="yellow", render_order=0),
        "Description": Description(
            name=t("features.trap_pit.name"),
            short=t("features.trap_pit.short"),
            long=t("features.trap_pit.long"),
        ),
        "Trap": Trap(damage="1d6", dc=12, hidden=True),
    }
