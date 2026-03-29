"""Teleport Trap — warps the victim to a random floor tile."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_teleport")
def create_teleport_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_blue", render_order=0),
        "Description": Description(
            name=t("features.trap_teleport.name"),
            short=t("features.trap_teleport.short"),
            long=t("features.trap_teleport.long"),
        ),
        "Trap": Trap(damage="0", dc=14, hidden=True, effect="teleport"),
    }
