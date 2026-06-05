"""Fixtures + guards for the Tier 2 WASM render bench.

Phase M of ``plans/wasm-render-caching.md``. Everything here is
opt-in: the ``perf`` marker is auto-skipped unless ``-m perf`` is
passed (see the root ``tests/conftest.py`` hook), and the bench
additionally skips gracefully when Playwright / Chromium are absent
so a fresh checkout's full run stays green without the ~150 MB dep.

Bootstrap the deps with ``make perf-bootstrap``.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = REPO_ROOT / "crates" / "nhc-render-wasm" / "pkg"
WASM_FILE = PKG_DIR / "nhc_render_wasm_bg.wasm"
CRATES_DIR = REPO_ROOT / "crates"


def require_playwright():
    """Return the Playwright sync entrypoint or skip.

    Skips (never fails) when the package is missing so the opt-in
    bench degrades cleanly on a machine that never bootstrapped.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip(
            "playwright not installed — run `make perf-bootstrap`",
        )
    return sync_playwright


def require_fresh_wasm_bundle():
    """Guard against timing a stale ``pkg/`` artifact.

    Tier 2 measures the built bundle, so a forgotten
    ``make wasm-build`` would silently time old code. Missing bundle
    → skip (nothing to measure); present-but-stale → FAIL loudly so
    the operator rebuilds. Never auto-builds (no slow release build
    buried in a test).
    """
    if not WASM_FILE.exists():
        pytest.skip(
            f"{WASM_FILE.relative_to(REPO_ROOT)} missing — "
            f"run `make wasm-build`",
        )
    bundle_mtime = WASM_FILE.stat().st_mtime
    newest_src = 0.0
    newest_path = None
    # Only sources that feed the bundle: crate src/ trees + Cargo
    # manifests. Test/bench files (crates/*/tests, benches) don't
    # affect the compiled wasm, so they must not trigger a rebuild
    # demand.
    candidates = list(CRATES_DIR.glob("*/src/**/*.rs"))
    candidates += list(CRATES_DIR.glob("*/Cargo.toml"))
    for src in candidates:
        m = src.stat().st_mtime
        if m > newest_src:
            newest_src, newest_path = m, src
    if newest_src > bundle_mtime:
        rel = newest_path.relative_to(REPO_ROOT) if newest_path else "?"
        pytest.fail(
            f"WASM bundle is stale: {rel} is newer than "
            f"{WASM_FILE.relative_to(REPO_ROOT)} — run `make wasm-build` "
            f"before benching (Tier 2 must measure current code)",
        )


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Repo-rooted static handler with WASM/NIR MIME types."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".nir": "application/octet-stream",
        ".js": "text/javascript",
        ".html": "text/html",
    }

    def log_message(self, *args):  # noqa: D401 - silence per-request noise
        pass


@pytest.fixture(scope="session")
def static_server():
    """Serve the repo over localhost so module imports + wasm
    streaming-instantiate exercise the real fetch path. Yields the
    base URL (ephemeral port)."""
    handler = functools.partial(_QuietHandler, directory=str(REPO_ROOT))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
