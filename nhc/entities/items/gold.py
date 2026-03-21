"""Gold coins — currency."""

from nhc.entities.components import Description, Renderable
from nhc.entities.registry import EntityRegistry


@EntityRegistry.register_item("gold")
def create_gold() -> dict:
    return {
        "Renderable": Renderable(glyph="$", color="bright_yellow", render_order=1),
        "Description": Description(
            name="Gold",
            short="a pile of gold coins",
            long="Tarnished coins bearing an unfamiliar crest. "
                 "Still good enough to spend.",
        ),
        "Gold": True,  # Tag component
    }
