"""Alarm Trap — piercing sound alerts all creatures on the level."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_feature("trap_alarm")
def create_alarm_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="bright_magenta", render_order=0),
        "Description": Description(
            name=t("features.trap_alarm.name"),
            short=t("features.trap_alarm.short"),
            long=t("features.trap_alarm.long"),
        ),
        "Trap": Trap(damage="0", dc=14, hidden=True, effect="alarm"),
    }
