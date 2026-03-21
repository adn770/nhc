"""Scroll of Lightning Bolt — ranged damage consumable."""

from nhc.entities.components import Consumable, Description, Renderable
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("scroll_lightning")
def create_scroll_lightning() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": Description(
            name="Scroll of Lightning",
            short="a crackling scroll",
            long="A parchment scroll inscribed with arcane symbols. "
                 "Lightning arcs between the letters.",
        ),
        "Consumable": Consumable(effect="damage_nearest", dice="3d6", slots=1),
    }
