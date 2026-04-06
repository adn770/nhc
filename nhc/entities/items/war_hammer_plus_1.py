"""Magic War Hammer +1 — enchanted war hammer."""

from nhc.entities.components import Enchanted, Renderable, Weapon
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("war_hammer_plus_1")
def create_war_hammer_plus_1() -> dict:
    return {
        "Renderable": Renderable(glyph=")", color="bright_cyan", render_order=1),
        "Description": item_desc("war_hammer_plus_1"),
        "Weapon": Weapon(damage="1d10", type="melee", slots=1, magic_bonus=1),
        "Enchanted": Enchanted(),
    }
