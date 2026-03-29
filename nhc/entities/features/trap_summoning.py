"""Summoning Trap — conjures hostile creatures nearby."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_summoning")
def create_summoning_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_white", render_order=0),
        "Description": Description(
            name=t("features.trap_summoning.name"),
            short=t("features.trap_summoning.short"),
            long=t("features.trap_summoning.long"),
        ),
        "Trap": Trap(damage="0", dc=15, hidden=True, effect="summoning"),
    }
