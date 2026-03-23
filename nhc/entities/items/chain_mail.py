"""Item — chain mail."""

from nhc.entities.components import Armor, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("chain_mail")
def create_chain_mail() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": item_desc("chain_mail"),
        "Armor": Armor(slot="body", defense=14, slots=3),
    }
