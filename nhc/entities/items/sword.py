"""Sword — standard melee weapon."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("sword")
def create_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="cyan", render_order=1),
        "Description": Description(
            name="Sword",
            short="a steel sword",
            long="A well-balanced blade of tempered steel, worn but sharp.",
        ),
        "Weapon": Weapon(damage="1d8", type="melee", slots=1),
    }
