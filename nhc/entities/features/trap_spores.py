"""Hallucinogenic Spores Trap — fungal cloud causes confusion."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_spores")
def create_spores_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="magenta", render_order=0),
        "Description": Description(
            name=t("features.trap_spores.name"),
            short=t("features.trap_spores.short"),
            long=t("features.trap_spores.long"),
        ),
        "Trap": Trap(damage="0", dc=13, hidden=True, effect="spores"),
    }
