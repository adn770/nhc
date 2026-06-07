"""Tests for the automatic crash-report writer.

``write_crash_report`` snapshots a crashed game session into
``<data_dir>/crashes/<kind>_<sid>_<utc_ts>Z.tar.gz`` reusing the
debug bundle, and degrades to a traceback-only tarball when the full
bundle cannot be built (e.g. a half-initialized game after a
generation crash).
"""

import tarfile
import time

import pytest

from nhc.web.app import create_app
from nhc.web.config import WebConfig
from nhc.web.crash_report import write_crash_report
from nhc.web.ws import _run_ws_session


@pytest.fixture
def client_with_data_dir(tmp_path):
    config = WebConfig(max_sessions=4, data_dir=tmp_path)
    app = create_app(config)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _new_session(c):
    """Create a real dungeon session and return (session, app)."""
    resp = c.post("/api/game/new", json={"world": "dungeon"})
    assert resp.status_code == 201
    sid = resp.get_json()["session_id"]
    session = c.application.config["SESSIONS"].get(sid)
    assert session is not None and session.game is not None
    return session, c.application


def _boom(message):
    """Return a caught exception carrying a real traceback."""
    try:
        raise ValueError(message)
    except ValueError as exc:
        return exc


class TestWriteCrashReport:
    def _args(self, app):
        config = app.config["NHC_CONFIG"]
        return {
            "data_dir": config.data_dir,
            "log_path": app.config.get("LOG_PATH", ""),
        }

    def test_writes_bundle_into_crashes_dir(self, client_with_data_dir):
        session, app = _new_session(client_with_data_dir)
        exc = _boom("kaboom in game loop")
        path = write_crash_report(
            session, kind="game_loop", exc=exc,
            **self._args(app),
        )
        assert path is not None
        assert path.exists()
        crashes = app.config["NHC_CONFIG"].data_dir / "crashes"
        files = list(crashes.glob("*.tar.gz"))
        assert len(files) == 1
        assert files[0].name.startswith("game_loop_")
        assert files[0].name.endswith("Z.tar.gz")

    def test_kind_prefix_in_filename(self, client_with_data_dir):
        session, app = _new_session(client_with_data_dir)
        path = write_crash_report(
            session, kind="gen", exc=_boom("gen failed"),
            **self._args(app),
        )
        assert path.name.startswith("gen_")

    def test_report_txt_has_traceback_and_metadata(
            self, client_with_data_dir):
        session, app = _new_session(client_with_data_dir)
        path = write_crash_report(
            session, kind="game_loop",
            exc=_boom("trace me please"),
            **self._args(app),
        )
        with tarfile.open(str(path), "r:gz") as tar:
            assert "report.txt" in tar.getnames()
            body = tar.extractfile("report.txt").read().decode("utf-8")
        assert "trace me please" in body
        assert "ValueError" in body
        assert "Traceback" in body
        assert "game_loop" in body
        assert session.session_id in body

    def test_full_bundle_includes_game_state(self, client_with_data_dir):
        session, app = _new_session(client_with_data_dir)
        path = write_crash_report(
            session, kind="game_loop", exc=_boom("x"),
            **self._args(app),
        )
        with tarfile.open(str(path), "r:gz") as tar:
            names = tar.getnames()
        # The full debug bundle contributes a game_state export.
        assert any(n.startswith("exports/game_state_") for n in names)

    def test_no_data_dir_is_noop(self, client_with_data_dir):
        session, app = _new_session(client_with_data_dir)
        path = write_crash_report(
            session, data_dir=None, log_path="",
            kind="game_loop", exc=_boom("x"),
        )
        assert path is None

    def test_falls_back_to_traceback_only(
            self, client_with_data_dir, monkeypatch):
        session, app = _new_session(client_with_data_dir)

        def _explode(*a, **k):
            raise RuntimeError("bundle builder is broken")

        monkeypatch.setattr(
            "nhc.web.crash_report.build_debug_tar", _explode,
        )
        path = write_crash_report(
            session, kind="gen", exc=_boom("original crash"),
            **self._args(app),
        )
        # Crash report is still written despite the bundle failure.
        assert path is not None and path.exists()
        with tarfile.open(str(path), "r:gz") as tar:
            names = tar.getnames()
            body = tar.extractfile("report.txt").read().decode("utf-8")
        assert "report.txt" in names
        # Only the traceback survives — no full game-state export.
        assert not any(
            n.startswith("exports/game_state_") for n in names)
        assert "original crash" in body


class _FakeWS:
    """Minimal WebSocket stand-in for driving _run_ws_session."""

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def receive(self, timeout=None):
        time.sleep(0.01)
        return None


class TestGameLoopCrashWiring:
    """An unhandled exception in the game loop writes a crash report."""

    def test_game_loop_exception_writes_report(
            self, client_with_data_dir, monkeypatch):
        session, app = _new_session(client_with_data_dir)
        sessions = app.config["SESSIONS"]

        async def _boom_run():
            raise ValueError("game loop exploded")

        monkeypatch.setattr(session.game, "run", _boom_run)

        _run_ws_session(
            _FakeWS(), session, sessions, session.session_id,
            app=app, start_game_loop=True,
        )

        crashes = app.config["NHC_CONFIG"].data_dir / "crashes"
        files = list(crashes.glob("game_loop_*.tar.gz"))
        assert len(files) == 1
        with tarfile.open(str(files[0]), "r:gz") as tar:
            body = tar.extractfile("report.txt").read().decode("utf-8")
        assert "game loop exploded" in body


class TestGenCrashWiring:
    """A dungeon-generation failure during /api/game/new writes a
    crash report and the endpoint still reports the failure."""

    def test_initialize_failure_writes_report(
            self, client_with_data_dir, monkeypatch):
        def _boom_init(self, *a, **k):
            raise RuntimeError("dungeon generation exploded")

        monkeypatch.setattr(
            "nhc.core.game.Game.initialize", _boom_init,
        )
        resp = client_with_data_dir.post(
            "/api/game/new", json={"world": "dungeon"},
        )
        assert resp.status_code == 500

        config = client_with_data_dir.application.config["NHC_CONFIG"]
        files = list((config.data_dir / "crashes").glob("gen_*.tar.gz"))
        assert len(files) == 1
        with tarfile.open(str(files[0]), "r:gz") as tar:
            assert "report.txt" in tar.getnames()
            body = tar.extractfile("report.txt").read().decode("utf-8")
        assert "dungeon generation exploded" in body
        assert "gen" in body
