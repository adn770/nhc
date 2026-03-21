"""Short Sword — light melee weapon."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("short_sword")
def create_short_sword() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_white", render_order=1),
        "Description": Description(
            name="Short Sword",
            short="a short sword",
            long="A compact blade favored by skirmishers. "
                 "Well-suited for close quarters.",
        ),
        "Weapon": Weapon(damage="1d6", type="melee", slots=1),
    }
