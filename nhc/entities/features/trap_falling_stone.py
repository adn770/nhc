"""Falling Stone Trap — a heavy stone drops from the ceiling."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_falling_stone")
def create_falling_stone_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_black", render_order=0),
        "Description": Description(
            name=t("features.trap_falling_stone.name"),
            short=t("features.trap_falling_stone.short"),
            long=t("features.trap_falling_stone.long"),
        ),
        "Trap": Trap(damage="2d6", dc=14, hidden=True, effect="falling_stone"),
    }
