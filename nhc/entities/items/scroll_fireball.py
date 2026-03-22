"""Scroll of Fireball — explodes in 20ft radius. (BEB: Bola de foc)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_fireball")
def create_scroll_fireball() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_red",
                                 render_order=1),
        "Description": item_desc("scroll_fireball"),
        # fireball: hits all visible creatures; half damage on DEX save
        "Consumable": Consumable(effect="fireball", dice="3d6", slots=1),
    }
