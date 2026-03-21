"""Healing Potion — restores hit points."""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("healing_potion")
def create_healing_potion() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="red", render_order=1),
        "Description": Description(
            name="Healing Potion",
            short="a crimson potion",
            long="A small glass vial filled with a glowing red liquid. "
                 "It smells faintly of iron and herbs.",
        ),
        "Consumable": Consumable(effect="heal", dice="2d4+2", slots=1),
    }
