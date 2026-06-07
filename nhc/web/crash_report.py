"""Automatic crash reporting for the web server.

When a game session dies on an unhandled exception — the game loop
throwing, or dungeon generation blowing up during ``initialize`` —
:func:`write_crash_report` snapshots the session into a debug bundle
so the failure can be triaged offline. It mirrors the tester
bug-report flow but is triggered by the server itself, writes to a
separate ``<data_dir>/crashes/`` directory, and auto-generates the
``report.txt`` from the traceback.

The writer is defensive on purpose: a crash often leaves the game in
a half-built state where the full bundle builder would itself raise.
In that case it degrades to a traceback-only tarball rather than
losing the report.
"""

from __future__ import annotations

import io
import logging
import tarfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from nhc.web.debug_bundle import build_debug_tar

logger = logging.getLogger(__name__)


def _format_report(session, *, kind: str, exc: BaseException | None) -> str:
    """Compose the human-readable ``report.txt`` for a crash."""
    game = getattr(session, "game", None)
    lines = [
        "NHC automatic crash report",
        f"kind: {kind}",
        f"timestamp: {datetime.now(timezone.utc).isoformat()}",
        f"session: {getattr(session, 'session_id', '?')}",
        f"player: {getattr(session, 'player_id', None) or 'anon'}",
    ]
    # Best-effort game metadata — the game may be half-initialized.
    for label, attr in (("turn", "turn"), ("seed", "seed"),
                        ("world_type", "world_type")):
        try:
            value = getattr(game, attr, None)
            if value is not None:
                lines.append(f"{label}: {value}")
        except Exception:
            pass
    lines.append("")
    if exc is not None:
        lines.append("".join(traceback.format_exception(exc)).rstrip())
    else:
        lines.append("(no exception captured)")
    return "\n".join(lines) + "\n"


def _traceback_only_tar(report_txt: str) -> bytes:
    """Build a minimal tarball holding just ``report.txt``."""
    data = report_txt.encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="report.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def write_crash_report(
    session,
    *,
    data_dir: Path | None,
    log_path: str = "",
    kind: str = "crash",
    exc: BaseException | None = None,
) -> Path | None:
    """Write a crash bundle for ``session`` to ``<data_dir>/crashes/``.

    Returns the path written, or ``None`` when ``data_dir`` is not
    configured (the dev/no-persistence case). The full debug bundle is
    attempted first; if it raises, the report degrades to a
    traceback-only tarball so a crash is never silently lost.
    """
    if not data_dir:
        return None

    report_txt = _format_report(session, kind=kind, exc=exc)
    try:
        tar_bytes = build_debug_tar(
            session, log_path=log_path,
            extra_entries=[("report.txt", report_txt)],
        )
    except Exception:
        logger.exception(
            "Crash bundle build failed for %s; "
            "falling back to traceback-only report",
            getattr(session, "session_id", "?"),
        )
        tar_bytes = _traceback_only_tar(report_txt)

    crashes_dir = Path(data_dir) / "crashes"
    crashes_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    sid = getattr(session, "session_id", "unknown")[:12]
    path = crashes_dir / f"{kind}_{sid}_{ts}.tar.gz"
    path.write_bytes(tar_bytes)
    logger.error(
        "CRASH report written: %s (%d bytes, kind=%s, session=%s)",
        path, len(tar_bytes), kind,
        getattr(session, "session_id", "?"),
    )
    return path
