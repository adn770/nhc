"""Per-NPC chatter on empty rumour pool.

``BumpAction`` routes every ``RumorVendor`` bump into the same
action. Before this change the action's empty-pool fallback only
knew how to roll from ``innkeeper.chatter``, so farmers and
orchardists parroted tavern-keeper lines about polishing mugs
and free fires — disconnected from the NPC's actual role.

Now each NPC factory stamps ``RumorVendor(chatter_table=...)``
and the action reads the tag and rolls from that table. These
tests pin the invariants:

- factories wire the expected table names.
- ``_on_empty_pool`` rolls from the vendor's own table.
- a vendor with no ``chatter_table`` falls back quietly (no
  innkeeper lines leaking onto a non-innkeeper NPC).
"""

from __future__ import annotations

import pytest

from nhc.core.actions._rumor_vendor import RumorVendorInteractAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent
from nhc.entities.components import (
    BlocksMovement, Health, Player, Position, Renderable, RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import Biome, HexCell, HexFeatureType, HexWorld
from nhc.i18n import init as i18n_init


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


_EXPECTED_TABLES: dict[str, str] = {
    "innkeeper": "innkeeper.chatter",
    "farmer": "farmer.chatter",
    "orchardist": "orchardist.chatter",
    "campsite_traveller": "campsite.chatter",
}


@pytest.mark.parametrize(
    "creature_id,expected_table", sorted(_EXPECTED_TABLES.items()),
)
def test_factory_wires_chatter_table(
    creature_id: str, expected_table: str,
) -> None:
    components = EntityRegistry.get_creature(creature_id)
    vendor = components.get("RumorVendor")
    assert vendor is not None, (
        f"{creature_id} must have a RumorVendor component"
    )
    assert vendor.chatter_table == expected_table, (
        f"{creature_id} should chat from {expected_table!r}, "
        f"got {vendor.chatter_table!r}"
    )


def _mini_hex_world() -> HexWorld:
    hw = HexWorld(pack_id="test", seed=0, width=3, height=3)
    for q in range(2):
        for r in range(2):
            hw.cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                feature=HexFeatureType.NONE,
                biome=Biome.GREENLANDS,
            )
    hw.active_rumors = []
    return hw


def _make_player(world: World, x: int = 0, y: int = 0) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="settle"),
        "Player": Player(),
        "Health": Health(current=10, maximum=10),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=1, wisdom=1, charisma=1,
        ),
        "Renderable": Renderable(
            glyph="@", color="white", render_order=10,
        ),
    })


def _make_vendor(
    world: World, x: int, y: int, chatter_table: str | None,
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="settle"),
        "Renderable": Renderable(
            glyph="F", color="bright_yellow", render_order=2,
        ),
        "BlocksMovement": BlocksMovement(),
        "RumorVendor": RumorVendor(chatter_table=chatter_table),
    })


@pytest.mark.asyncio
async def test_empty_pool_rolls_from_farmer_chatter(monkeypatch) -> None:
    """Bumping a farmer with an empty rumour pool rolls from
    ``farmer.chatter`` — not ``innkeeper.chatter``."""
    world = World()
    pid = _make_player(world)
    vid = _make_vendor(world, x=1, y=0, chatter_table="farmer.chatter")
    hw = _mini_hex_world()

    seen: list[str] = []

    def fake_roll_ephemeral(table_id, *, lang, context=None):
        seen.append(table_id)

        class _R:
            text = f"<<{table_id}>>"

        return _R()

    monkeypatch.setattr(
        "nhc.tables.roll_ephemeral", fake_roll_ephemeral,
    )
    monkeypatch.setattr(
        "nhc.core.actions._rumor_vendor.roll_ephemeral",
        fake_roll_ephemeral,
        raising=False,
    )
    action = RumorVendorInteractAction(
        actor=pid, vendor_id=vid, hex_world=hw,
    )
    events = await action.execute(world, None)
    msgs = [e.text for e in events if isinstance(e, MessageEvent)]
    assert "farmer.chatter" in seen, (
        f"expected a roll on farmer.chatter, got {seen}"
    )
    assert "innkeeper.chatter" not in seen
    assert any("farmer.chatter" in m for m in msgs), (
        f"expected chatter in emitted messages, got {msgs}"
    )


@pytest.mark.asyncio
async def test_empty_pool_no_chatter_table_stays_quiet() -> None:
    """A RumorVendor without a chatter_table must not borrow
    innkeeper flavour. It still emits a neutral "no news" message
    so the player gets feedback."""
    world = World()
    pid = _make_player(world)
    vid = _make_vendor(world, x=1, y=0, chatter_table=None)
    hw = _mini_hex_world()

    action = RumorVendorInteractAction(
        actor=pid, vendor_id=vid, hex_world=hw,
    )
    events = await action.execute(world, None)
    msgs = [e.text for e in events if isinstance(e, MessageEvent)]
    assert msgs, "action must emit at least one message"
    # Neither the stock innkeeper polish-mug line nor any other
    # innkeeper-table entry should surface from a vendor that
    # hasn't opted into a chatter table.
    joined = " ".join(msgs)
    assert "innkeeper" not in joined.lower()
    assert "polishes a mug" not in joined
