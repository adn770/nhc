"""Verify the hexcrawl module skeleton and bundled testland pack are
in place. Tests under ``tests/unit/hexcrawl/`` are grouped by
directory; no custom pytest marker is required.
"""

from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_hexcrawl_module_importable() -> None:
    import nhc.hexcrawl  # noqa: F401


def test_testland_pack_file_exists() -> None:
    pack = _project_root() / "content" / "testland" / "pack.yaml"
    assert pack.is_file(), pack
