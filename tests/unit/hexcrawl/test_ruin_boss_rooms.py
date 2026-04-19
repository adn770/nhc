"""Ruin descent Floor 3 boss rooms (M10 of biome-features v2).

design/biome_features.md §8 calls for the deepest ruin descent
floor (Floor 3, depth 4) to carry a themed boss encounter. Exactly
one room on that floor should be tagged "boss" and seeded with a
faction leader drawn from FACTION_LEADERS; all shallower floors
(Floors 1 + 2) keep the v1 no-boss shape.
"""

from __future__ import annotations

import asyncio

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
from nhc.hexcrawl.model import (
    Biome, DungeonRef, HexCell, HexFeatureType, HexWorld,
)
from nhc.i18n import init as i18n_init


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


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


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(), backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path, seed=42,
    )
    g.initialize()
    return g


def _seed_ruin(
    g: Game, biome: Biome, faction: str,
) -> HexCell:
    g.hex_world = HexWorld(
        pack_id="t", seed=42, width=1, height=1,
    )
    cell = HexCell(
        coord=HexCoord(0, 0), biome=biome,
        feature=HexFeatureType.RUIN,
        dungeon=DungeonRef(
            template="procedural:ruin",
            site_kind="ruin",
            faction=faction,
        ),
    )
    g.hex_world.set_cell(cell)
    g.hex_world.visit(cell.coord)
    g.hex_player_position = cell.coord
    return cell


async def _descend_onto_floor(
    g: Game, biome: Biome, faction: str, floors_down: int,
) -> None:
    cell = _seed_ruin(g, biome, faction)
    await g._enter_walled_site(cell.coord, "ruin")
    assert g._active_site is not None
    building = g._active_site.buildings[0]
    g.level = building.ground
    stair_xy = next(
        (x, y)
        for y in range(building.ground.height)
        for x in range(building.ground.width)
        if building.ground.tiles[y][x].feature == "stairs_down"
    )
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = stair_xy
    pos.level_id = building.ground.id
    from nhc.core.events import LevelEntered
    for _ in range(floors_down):
        new_depth = g.level.depth + 1
        g._on_level_entered(LevelEntered(depth=new_depth))


def _count_boss_rooms(level) -> int:
    return sum(1 for r in level.rooms if "boss" in r.tags)


def _boss_room(level):
    return next((r for r in level.rooms if "boss" in r.tags), None)


# ── Boss room tagging ─────────────────────────────────────────────────


class TestBossRoomTagging:
    def test_ruin_descent_floor_3_has_exactly_one_boss_tagged_room(
        self, tmp_path,
    ):
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, Biome.FOREST, "cultist", 3)
            assert g.level.depth == 4
            assert _count_boss_rooms(g.level) == 1

        asyncio.run(_run())

    def test_ruin_descent_floor_1_has_no_boss_rooms(self, tmp_path):
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, Biome.FOREST, "cultist", 1)
            assert g.level.depth == 2
            assert _count_boss_rooms(g.level) == 0

        asyncio.run(_run())

    def test_ruin_descent_floor_2_has_no_boss_rooms(self, tmp_path):
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, Biome.FOREST, "cultist", 2)
            assert g.level.depth == 3
            assert _count_boss_rooms(g.level) == 0

        asyncio.run(_run())


# ── Boss content ──────────────────────────────────────────────────────


class TestBossContent:
    @pytest.mark.parametrize("biome,faction", [
        (Biome.FOREST, "bandit"),
        (Biome.FOREST, "beast"),
        (Biome.FOREST, "cultist"),
        (Biome.DEADLANDS, "undead"),
        (Biome.MARSH, "lizardman"),
        (Biome.SANDLANDS, "gnoll"),
        (Biome.ICELANDS, "frozen_dead"),
        (Biome.ICELANDS, "yeti"),
    ])
    def test_boss_room_contains_a_faction_leader_creature(
        self, tmp_path, biome, faction,
    ):
        from nhc.dungeon.populator import FACTION_LEADERS
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, biome, faction, 3)
            boss_room = _boss_room(g.level)
            assert boss_room is not None

            expected_leaders = {
                cid for cid, _ in FACTION_LEADERS[faction]
            }
            rect = boss_room.rect
            found = []
            for ent in g.level.entities:
                if ent.entity_type != "creature":
                    continue
                if (rect.x <= ent.x < rect.x2
                        and rect.y <= ent.y < rect.y2):
                    found.append(ent.entity_id)
            assert any(cid in expected_leaders for cid in found), (
                f"{faction}: no leader found in boss room; "
                f"placed={found}, expected={expected_leaders}"
            )

        asyncio.run(_run())

    def test_boss_creature_is_tougher_than_rank_and_file(self, tmp_path):
        """For every faction, the leader's max HP should exceed the
        pool's weighted-average member HP (a loose "clearly tougher"
        check; matches the design spirit without fighting per-pool
        balance)."""
        from nhc.dungeon.populator import FACTION_LEADERS, FACTION_POOLS
        weak_factions = []
        for faction, leaders in FACTION_LEADERS.items():
            pool = FACTION_POOLS[faction]
            total_weight = sum(w for _, w in pool)
            avg_hp = sum(
                EntityRegistry.get_creature(cid)["Health"].maximum * w
                for cid, w in pool
            ) / total_weight
            for leader_id, _ in leaders:
                leader_hp = (
                    EntityRegistry.get_creature(leader_id)[
                        "Health"
                    ].maximum
                )
                if leader_hp <= avg_hp:
                    weak_factions.append(
                        f"{faction}:{leader_id} "
                        f"(leader={leader_hp}, avg={avg_hp:.1f})"
                    )
        assert not weak_factions, (
            f"Leader not tougher than rank-and-file: {weak_factions}"
        )


# ── Populator contract ────────────────────────────────────────────────


class TestPopulatorContract:
    def test_boss_is_in_populator_special_tags(self):
        """populate_level must list 'boss' among tags that keep a
        room out of the regular-creature placement path."""
        from pathlib import Path
        import re
        src = (
            Path(__file__).resolve().parents[3]
            / "nhc" / "dungeon" / "populator.py"
        ).read_text()
        match = re.search(
            r"special_tags\s*=\s*\{([^}]*)\}", src, flags=re.DOTALL,
        )
        assert match is not None, (
            "special_tags set literal not found in populator.py"
        )
        body = match.group(1)
        assert '"boss"' in body, (
            f"'boss' missing from special_tags: {body!r}"
        )

    def test_boss_room_has_no_non_boss_creatures(self, tmp_path):
        """Only the leader(s) should live in the boss room -- no
        regular-pool creatures should have been placed there."""
        from nhc.dungeon.populator import FACTION_LEADERS
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, Biome.FOREST, "cultist", 3)
            boss_room = _boss_room(g.level)
            assert boss_room is not None
            rect = boss_room.rect
            leader_ids = {
                cid for cid, _ in FACTION_LEADERS["cultist"]
            }
            for ent in g.level.entities:
                if ent.entity_type != "creature":
                    continue
                if not (rect.x <= ent.x < rect.x2
                        and rect.y <= ent.y < rect.y2):
                    continue
                assert ent.entity_id in leader_ids, (
                    f"non-leader creature {ent.entity_id!r} in boss "
                    f"room"
                )

        asyncio.run(_run())
