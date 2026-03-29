"""Arrow Trap — fires a hidden crossbow bolt."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_arrow")
def create_arrow_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="white", render_order=0),
        "Description": Description(
            name=t("features.trap_arrow.name"),
            short=t("features.trap_arrow.short"),
            long=t("features.trap_arrow.long"),
        ),
        "Trap": Trap(damage="1d6", dc=13, hidden=True, effect="arrow"),
    }
