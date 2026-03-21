"""Pit Trap — hidden hazard."""

from nhc.entities.components import Description, Renderable, Trap
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_feature("trap_pit")
def create_pit_trap() -> dict:
    return {
        "Renderable": Renderable(glyph="^", color="yellow", render_order=0),
        "Description": Description(
            name="Pit Trap",
            short="a concealed pit",
            long="The flagstones here look subtly different — lighter, "
                 "as if placed more recently.",
        ),
        "Trap": Trap(damage="1d6", dc=12, hidden=True),
    }
