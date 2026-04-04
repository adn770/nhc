"""Trap Door — hidden floor hatch that drops the victim to a lower level."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_trapdoor")
def create_trapdoor_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="brown", render_order=0),
        "Description": Description(
            name=t("features.trap_trapdoor.name"),
            short=t("features.trap_trapdoor.short"),
            long=t("features.trap_trapdoor.long"),
        ),
        "Trap": Trap(damage="2d6", dc=14, hidden=True, effect="trapdoor"),
    }
