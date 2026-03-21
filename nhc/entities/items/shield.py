"""Shield — defensive equipment."""

from nhc.entities.components import Description, Renderable, Weapon
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("shield")
def create_shield() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": Description(
            name="Shield",
            short="a wooden shield",
            long="A round wooden shield reinforced with iron bands. "
                 "Grants +1 armor defense.",
        ),
        "Shield": True,  # Tag component for armor bonus
    }
