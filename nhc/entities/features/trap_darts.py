"""Darts Trap — three poison-tipped darts fire from the wall."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_darts")
def create_darts_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="green", render_order=0),
        "Description": Description(
            name=t("features.trap_darts.name"),
            short=t("features.trap_darts.short"),
            long=t("features.trap_darts.long"),
        ),
        "Trap": Trap(damage="3d4", dc=13, hidden=True, effect="darts"),
    }
