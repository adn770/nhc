"""Dagger — light melee weapon."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("dagger")
def create_dagger() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="white", render_order=1),
        "Description": Description(
            name="Dagger",
            short="a sharp dagger",
            long="A short blade with a leather-wrapped grip. "
                 "Quick to draw, quick to cut.",
        ),
        "Weapon": Weapon(damage="1d4", type="melee", slots=1),
    }
