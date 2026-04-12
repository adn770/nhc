"""Tests for the scoring function and leaderboard persistence."""

from __future__ import annotations

import json

import pytest

from nhc.web.leaderboard import (
    Leaderboard,
    LeaderboardEntry,
    compute_score,
)


class TestComputeScore:
    def test_baseline_score_matches_formula(self):
        # xp + gold + (depth-1)*100 + victory_bonus
        assert compute_score(xp=0, gold=0, depth=1, won=False) == 0

    def test_depth_bonus(self):
        assert compute_score(xp=0, gold=0, depth=5, won=False) == 400

    def test_xp_and_gold_are_additive(self):
        assert compute_score(xp=120, gold=50, depth=1, won=False) == 170

    def test_victory_bonus_applied_on_win(self):
        base = compute_score(xp=200, gold=40, depth=3, won=False)
        won = compute_score(xp=200, gold=40, depth=3, won=True)
        assert won - base == 5000

    def test_negative_inputs_clamped_to_zero(self):
        # A dead player with buggy state should never produce
        # a negative leaderboard score.
        assert compute_score(xp=-10, gold=-5, depth=0, won=False) == 0


class TestLeaderboardPersistence:
    def test_submit_and_top(self, tmp_path):
        lb = Leaderboard(tmp_path / "leaderboard.json")
        lb.load()
        lb.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=500, depth=3, turn=120, won=False,
            killed_by="goblin", timestamp=1000.0,
        ))
        lb.submit(LeaderboardEntry(
            player_id="p2", name="Bob",
            score=1200, depth=5, turn=300, won=True,
            killed_by="", timestamp=1001.0,
        ))
        top = lb.top(10)
        assert len(top) == 2
        assert top[0].name == "Bob"
        assert top[1].name == "Alice"
        # rank starts at 1
        assert top[0].rank == 1
        assert top[1].rank == 2

    def test_top_limit(self, tmp_path):
        lb = Leaderboard(tmp_path / "leaderboard.json")
        lb.load()
        for i in range(25):
            lb.submit(LeaderboardEntry(
                player_id=f"p{i}", name=f"P{i}",
                score=i * 10, depth=1, turn=10, won=False,
                killed_by="rat", timestamp=float(i),
            ))
        assert len(lb.top(10)) == 10
        assert lb.top(10)[0].score == 240  # highest

    def test_persisted_across_instances(self, tmp_path):
        path = tmp_path / "leaderboard.json"
        lb1 = Leaderboard(path)
        lb1.load()
        lb1.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=777, depth=2, turn=50, won=False,
            killed_by="orc", timestamp=500.0,
        ))
        assert path.exists()
        # New instance reads what the first one wrote
        lb2 = Leaderboard(path)
        lb2.load()
        top = lb2.top(10)
        assert len(top) == 1
        assert top[0].name == "Alice"
        assert top[0].score == 777

    def test_load_missing_file_is_noop(self, tmp_path):
        lb = Leaderboard(tmp_path / "nope.json")
        lb.load()  # must not raise
        assert lb.top(10) == []

    def test_corrupt_file_is_tolerated(self, tmp_path):
        path = tmp_path / "leaderboard.json"
        path.write_text("{not valid json")
        lb = Leaderboard(path)
        lb.load()
        assert lb.top(10) == []

    def test_atomic_write_produces_valid_json(self, tmp_path):
        path = tmp_path / "leaderboard.json"
        lb = Leaderboard(path)
        lb.load()
        lb.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=42, depth=1, turn=5, won=False,
            killed_by="", timestamp=1.0,
        ))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "entries" in data
        assert len(data["entries"]) == 1
        assert data["entries"][0]["name"] == "Alice"

    def test_ties_broken_by_timestamp(self, tmp_path):
        """Same score → earlier submission ranks higher."""
        lb = Leaderboard(tmp_path / "leaderboard.json")
        lb.load()
        lb.submit(LeaderboardEntry(
            player_id="p1", name="First",
            score=100, depth=1, turn=10, won=False,
            killed_by="", timestamp=100.0,
        ))
        lb.submit(LeaderboardEntry(
            player_id="p2", name="Second",
            score=100, depth=1, turn=10, won=False,
            killed_by="", timestamp=200.0,
        ))
        top = lb.top(10)
        assert top[0].name == "First"
        assert top[1].name == "Second"

    def test_remove_player_entries(self, tmp_path):
        """remove_player_entries drops all entries for a given player."""
        lb = Leaderboard(tmp_path / "leaderboard.json")
        lb.load()
        lb.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=500, depth=3, turn=120, won=False,
            killed_by="goblin", timestamp=1000.0,
        ))
        lb.submit(LeaderboardEntry(
            player_id="p2", name="Bob",
            score=300, depth=2, turn=80, won=False,
            killed_by="rat", timestamp=1001.0,
        ))
        lb.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=700, depth=4, turn=200, won=False,
            killed_by="orc", timestamp=1002.0,
        ))
        removed = lb.remove_player_entries("p1")
        assert removed == 2
        top = lb.top(10)
        assert len(top) == 1
        assert top[0].name == "Bob"

    def test_remove_player_entries_persists(self, tmp_path):
        """Removal is persisted to disk."""
        path = tmp_path / "leaderboard.json"
        lb = Leaderboard(path)
        lb.load()
        lb.submit(LeaderboardEntry(
            player_id="p1", name="Alice",
            score=100, depth=1, turn=10, won=False,
            killed_by="", timestamp=1.0,
        ))
        lb.remove_player_entries("p1")
        lb2 = Leaderboard(path)
        lb2.load()
        assert lb2.top(10) == []

    def test_remove_player_entries_unknown_player(self, tmp_path):
        """Removing a non-existent player returns 0."""
        lb = Leaderboard(tmp_path / "leaderboard.json")
        lb.load()
        assert lb.remove_player_entries("nobody") == 0
