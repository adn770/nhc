"""Fire Trap — burst of flame on trigger."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_fire")
def create_fire_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_red", render_order=0),
        "Description": Description(
            name=t("features.trap_fire.name"),
            short=t("features.trap_fire.short"),
            long=t("features.trap_fire.long"),
        ),
        "Trap": Trap(damage="1d8", dc=13, hidden=True, effect="fire"),
    }
