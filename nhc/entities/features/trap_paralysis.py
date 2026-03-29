"""Paralysis Trap — cloud of paralyzing gas."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_paralysis")
def create_paralysis_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_cyan", render_order=0),
        "Description": Description(
            name=t("features.trap_paralysis.name"),
            short=t("features.trap_paralysis.short"),
            long=t("features.trap_paralysis.long"),
        ),
        "Trap": Trap(damage="0", dc=13, hidden=True, effect="paralysis"),
    }
