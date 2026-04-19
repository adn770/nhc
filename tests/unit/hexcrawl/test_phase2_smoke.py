"""Phase 2 integration smoke test.

Walks a single player through the full Phase 2 surface:

1. Start a HEX_EASY game.
2. Enter a settlement; merchant / priest / hirable adventurer
   spawn and the whole party comes inside.
3. Recruit the hirable henchman through :class:`RecruitAction`.
4. Exit the settlement; the hired henchman follows back to
   overland.
5. Enter a cave; the party is capped at :data:`MAX_HENCHMEN`
   with left-behinds keyed by ``Position.level_id == "overland"``.
6. Stage a Fight encounter and resolve it -- an arena Level
   loads with the rolled creatures.
7. Panic-flee from the arena -- player pops back to overland,
   HP drops, day clock advances.

The individual pieces have dedicated unit tests; this case
proves they compose end-to-end.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.actions._henchman import MAX_HENCHMEN, RecruitAction
from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.encounter_pipeline import Encounter, EncounterChoice
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import Biome, DungeonRef, HexFeatureType
from nhc.i18n import init as i18n_init


class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


@pytest.mark.asyncio
async def test_phase2_full_loop(tmp_path) -> None:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    coord = g.hex_player_position
    assert coord is not None

    # Force the start cell to be a settlement so step 1 is
    # deterministic regardless of the generator's feature roll.
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CITY
    cell.dungeon = DungeonRef(template="procedural:settlement")

    # ── 1. Enter the settlement ────────────────────────────────
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.level.metadata.theme == "town"
    # Settlement service NPCs live inside their tagged buildings
    # now -- shop holds the merchant, inn the adventurer /
    # innkeeper, temple the priest. They only materialise in the
    # ECS world when the player crosses the matching door.
    site = g._active_site
    assert site is not None
    shop = next(
        b for b in site.buildings
        if "shop" in b.ground.rooms[0].tags
    )
    inn = next(
        b for b in site.buildings
        if "inn" in b.ground.rooms[0].tags
    )
    temple = next(
        b for b in site.buildings
        if "temple" in b.ground.rooms[0].tags
    )

    # Step into the shop; merchant spawns.
    g._swap_to_building(shop, *shop.base_rect.center)
    merchants = [
        eid for eid, _ in g.world.query("ShopInventory")
        if g.world.get_component(eid, "TempleServices") is None
    ]
    assert len(merchants) == 1

    # Step into the temple; priest spawns.
    g._swap_to_building(temple, *temple.base_rect.center)
    priests = [eid for eid, _ in g.world.query("TempleServices")]
    assert len(priests) == 1

    # Step into the inn; hirable adventurer spawns.
    g._swap_to_building(inn, *inn.base_rect.center)
    unhired = [
        eid for eid, h in g.world.query("Henchman")
        if not h.hired
    ]
    assert len(unhired) == 1

    # ── 2. Recruit the henchman ────────────────────────────────
    adventurer_id = unhired[0]
    # Give the player enough gold.
    player = g.world.get_component(g.player_id, "Player")
    player.gold = 500
    # Move the player adjacent to the adventurer so the adjacency
    # check in RecruitAction passes.
    ppos = g.world.get_component(g.player_id, "Position")
    apos = g.world.get_component(adventurer_id, "Position")
    ppos.x, ppos.y = apos.x - 1, apos.y
    action = RecruitAction(
        actor=g.player_id, target=adventurer_id,
        max_party=MAX_HENCHMEN,
    )
    await action.execute(g.world, g.level)
    hench = g.world.get_component(adventurer_id, "Henchman")
    assert hench.hired is True
    assert hench.owner == g.player_id

    # ── 3. Exit the settlement; henchman moves to overland ────
    await g.exit_dungeon_to_hex()
    assert g.level is None
    hpos = g.world.get_component(adventurer_id, "Position")
    assert hpos.level_id == "overland"

    # ── 4. Enter a cave on the same hex (swap feature) ────────
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave")
    # Clear the stale town floor-cache entry so the cave loads
    # fresh instead of re-handing back the town Level.
    g._floor_cache.clear()
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.level.metadata.theme != "town"
    # Hired henchman followed because they fit under MAX_HENCHMEN.
    hpos = g.world.get_component(adventurer_id, "Position")
    assert hpos.level_id == g.level.id

    # ── 5. Stage + resolve a Fight encounter ──────────────────
    g.pending_encounter = Encounter(
        biome=Biome.GREENLANDS,
        creatures=["goblin", "kobold"],
    )
    g._encounter_rng = random.Random(1)
    arena_before = g.level
    await g.resolve_encounter(EncounterChoice.FIGHT)
    assert g.level is not None, (
        "FIGHT should swap self.level for the arena"
    )
    assert g.level is not arena_before
    assert any("arena" in r.tags for r in g.level.rooms)

    # ── 6. Panic flee the arena ───────────────────────────────
    hp = g.world.get_component(g.player_id, "Health")
    hp_before = hp.current
    clock_before = (g.hex_world.day, g.hex_world.time)
    await g.panic_flee()
    assert g.level is None, "panic flee must pop the arena"
    assert hp.current < hp_before
    assert (g.hex_world.day, g.hex_world.time) != clock_before

    # ── 7. Henchman followed the player back out ──────────────
    hpos = g.world.get_component(adventurer_id, "Position")
    assert hpos.level_id == "overland", (
        "hired henchman should exit with the player, got "
        f"level_id={hpos.level_id}"
    )
