"""Tests for --reset flag in nhc_web and WebConfig."""

import sys
from unittest.mock import patch

from nhc_web import parse_args
from nhc.web.app import create_app
from nhc.web.config import WebConfig


def test_webconfig_reset_defaults_false():
    """WebConfig.reset should default to False (recover autosave)."""
    config = WebConfig()
    assert config.reset is False


def test_webconfig_reset_true():
    """WebConfig.reset can be set to True."""
    config = WebConfig(reset=True)
    assert config.reset is True


def test_parse_args_reset_absent(monkeypatch):
    """--reset absent means args.reset is False."""
    monkeypatch.setattr(sys, "argv", ["nhc_web.py"])
    args = parse_args()
    assert args.reset is False


def test_parse_args_reset_present(monkeypatch):
    """--reset flag sets args.reset to True."""
    monkeypatch.setattr(sys, "argv", ["nhc_web.py", "--reset"])
    args = parse_args()
    assert args.reset is True


def test_game_new_passes_reset_flag():
    """POST /api/game/new should pass config.reset to Game()."""
    captured = {}

    class FakeGame:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.level = None
            self.renderer = kwargs.get("client")
            self.seed = 0

    async def fake_initialize(**kwargs):
        pass

    FakeGame.initialize = fake_initialize

    config = WebConfig(reset=True)
    app = create_app(config)

    with patch("nhc.core.game.Game", FakeGame):
        client = app.test_client()
        resp = client.post("/api/game/new", json={"lang": "en"})
        # Game() was called regardless of initialize outcome
        assert captured.get("reset") is True


def test_game_new_default_no_reset():
    """Without --reset, Game should get reset=False."""
    captured = {}

    class FakeGame:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.level = None
            self.renderer = kwargs.get("client")
            self.seed = 0

    async def fake_initialize(**kwargs):
        pass

    FakeGame.initialize = fake_initialize

    config = WebConfig(reset=False)
    app = create_app(config)

    with patch("nhc.core.game.Game", FakeGame):
        client = app.test_client()
        resp = client.post("/api/game/new", json={"lang": "en"})
        assert captured.get("reset") is False


def test_fresh_game_after_death(tmp_path, monkeypatch):
    """No autosave (deleted on death) creates a fresh game without --reset."""
    save_path = tmp_path / "autosave.nhc"
    monkeypatch.setattr("nhc.core.autosave._DEFAULT_PATH", save_path)
    monkeypatch.setattr("nhc.core.autosave._DEFAULT_DIR", tmp_path)

    # No autosave file on disk — simulates post-death state
    assert not save_path.exists()

    config = WebConfig(max_sessions=2, reset=False)
    app = create_app(config)
    app.config["TESTING"] = True

    with app.test_client() as client:
        # Dungeon-mode: asserts session.game.level is populated,
        # which is only the case for dungeon entries (hex-mode
        # games sit on an overland HexWorld until a feature is
        # entered).
        resp = client.post(
            "/api/game/new", json={"world": "dungeon"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "session_id" in data

        # Verify a fresh game was generated (not restored)
        sessions = client.application.config["SESSIONS"]
        session = sessions.get(data["session_id"])
        assert session.game is not None
        assert session.game.level is not None
        assert session.game.turn == 0
