"""Tests for ephemeral roll path."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from nhc.i18n import init as i18n_init
from nhc.tables import roll, roll_ephemeral
from nhc.tables.registry import GenTimeRNGRequiredError, TableRegistry


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tables" / "good"


def setup_module():
    i18n_init("en")


def test_ephemeral_roll_accepts_none_rng_uses_module_random() -> None:
    result = roll_ephemeral(
        "innkeeper.chatter", lang="en",
    )
    assert result.text
    assert result.entry_id


def test_gen_time_still_rejects_none_rng() -> None:
    """Regression guard: gen_time tables must refuse None rng."""
    TableRegistry._cache.clear()
    reg = TableRegistry.get_or_load("en", root=FIXTURES)
    with pytest.raises(GenTimeRNGRequiredError):
        reg.roll("example.greeting", rng=None, context={})
    TableRegistry._cache.clear()


def test_two_ephemeral_rolls_may_differ() -> None:
    """Over a large sample, ephemeral rolls should vary."""
    texts = {
        roll_ephemeral("innkeeper.chatter", lang="en").text
        for _ in range(50)
    }
    assert len(texts) > 1, "ephemeral rolls should vary"


@pytest.mark.asyncio
async def test_innkeeper_chatter_fires_on_visit() -> None:
    """When the rumor pool is empty, innkeeper emits chatter."""
    from nhc.core.actions._innkeeper import InnkeeperInteractAction
    from nhc.core.ecs import World
    from nhc.core.events import MessageEvent
    from nhc.entities.components import (
        AI, Health, Position, Renderable, RumorVendor, Stats,
    )
    from nhc.hexcrawl.model import Biome, HexCell, HexCoord, HexWorld

    world = World()
    pid = world.create_entity()
    world.add_component(pid, "Position", Position(x=0, y=0))
    world.add_component(pid, "Stats", Stats())
    inn_id = world.create_entity()
    world.add_component(inn_id, "Position", Position(x=1, y=0))
    world.add_component(
        inn_id, "RumorVendor",
        RumorVendor(chatter_table="innkeeper.chatter"),
    )

    hw = HexWorld(pack_id="test", seed=1, width=3, height=3)
    hw.set_cell(HexCell(
        coord=HexCoord(q=0, r=0),
        biome=Biome.GREENLANDS,
    ))
    hw.active_rumors = []

    action = InnkeeperInteractAction(
        actor=pid, innkeeper_id=inn_id, hex_world=hw,
    )
    events = await action.execute(world, None)
    # Should have the "none" message plus a chatter line
    msg_events = [e for e in events if isinstance(e, MessageEvent)]
    assert len(msg_events) >= 2, (
        f"expected at least 2 messages (status + chatter), "
        f"got {len(msg_events)}"
    )
