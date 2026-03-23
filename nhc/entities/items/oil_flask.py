"""Oil Flask — throwable fire, deals 1d8 damage."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("oil_flask")
def create_oil_flask() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_yellow", render_order=1),
        "Description": item_desc("oil_flask"),
        "Consumable": Consumable(effect="fireball", dice="1d8", slots=1),
    }
