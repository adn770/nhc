"""Debug bundle construction shared across the web server.

The debug bundle is a ``tar.gz`` snapshot of a game session — game
state JSON, layer state, autosave, server log, layer PNGs and the
browser console log. It backs three flows:

* the tester-mode bug-report endpoint (``submit_report``),
* the on-demand bundle download (``export_debug_bundle``),
* the automatic crash report (:mod:`nhc.web.crash_report`).

Keeping the builder module-level (rather than a closure inside the
Flask factory) lets the crash reporter reuse it without dragging the
whole application object along.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# Characters that NFKD does not decompose but that have an obvious
# ASCII equivalent for filename purposes.
_TRANSLIT = {
    ord("ø"): "o", ord("Ø"): "O",
    ord("æ"): "ae", ord("Æ"): "AE",
    ord("ß"): "ss",
    ord("ð"): "d", ord("Ð"): "D",
    ord("þ"): "th", ord("Þ"): "Th",
    ord("ł"): "l", ord("Ł"): "L",
}


def slug_player_name(name: str) -> str:
    """Produce a filesystem-safe slug from a player display name.

    Transliterates a small set of non-decomposable latin chars,
    NFKD-normalizes and strips combining marks, lowercases, then
    collapses any run of non-alphanumeric characters into a single
    underscore. An empty result falls back to ``player`` so the
    filename stem is always well-formed.
    """
    import re
    import unicodedata
    translit = name.translate(_TRANSLIT)
    nfkd = unicodedata.normalize("NFKD", translit)
    ascii_only = "".join(
        c for c in nfkd if not unicodedata.combining(c)
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only).strip("_")
    return slug.lower() or "player"


def build_debug_tar(session, *, log_path="", extra_entries=()) -> bytes:
    """Produce a debug tar.gz for ``session`` as raw bytes.

    ``log_path`` is the path to the server log to embed as
    ``nhc.log`` (empty or missing simply omits it). ``extra_entries``
    is an iterable of ``(arcname, text)`` pairs injected at the
    archive root — used by the tester bug-report flow to bundle the
    user's description as ``report.txt`` and by the crash reporter to
    bundle the traceback.
    """
    import io
    import json as _json
    import tarfile
    from datetime import datetime

    game = session.game
    client = game.renderer
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Force a fresh autosave so the bundle always contains
    # the current game state.
    if session.save_dir:
        from nhc.core.autosave import autosave as _autosave
        _autosave(game, session.save_dir, blocking=True)

    def _add_text(tar, name, text):
        data = text.encode("utf-8")
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # 1. Game state JSON (MCP expects exports/game_state_*.json)
        from nhc.core.save import _serialize_entities, _serialize_level
        level = game.level
        static, dynamic = client._gather_stats(
            game.world, game.player_id, game.turn, level)
        gen_params = (game.generation_params.to_dict()
                      if game.generation_params else None)
        state = {
            "timestamp": datetime.now().isoformat(),
            "turn": game.turn,
            "player_id": game.player_id,
            "seed": game.seed,
            "level_id": level.id if level else None,
            "floor_svg_id": client.floor_svg_id,
            "generation_params": gen_params,
            "stats": {**static, **dynamic},
            "ecs": _serialize_entities(game.world),
        }
        if level:
            state["entities"] = client._gather_entities(
                game.world, level, game.player_id)
            state["level"] = _serialize_level(level)
        # Hex world state (when in hexcrawl mode).
        hex_world = getattr(game, "hex_world", None)
        if hex_world:
            from nhc.core.save import _serialize_hex_world
            state["hex_world"] = _serialize_hex_world(hex_world)
            state["hex_player"] = (
                {"q": game.hex_player_position.q,
                 "r": game.hex_player_position.r}
                if game.hex_player_position else None
            )
        _add_text(tar, f"exports/game_state_{ts}.json",
                  _json.dumps(state, indent=2))

        # 2. Layer state JSON (dungeon mode only)
        if level:
            explored = [[x, y]
                        for y in range(level.height)
                        for x in range(level.width)
                        if (t := level.tile_at(x, y))
                        and t.explored]
            layer = {
                "timestamp": datetime.now().isoformat(),
                "turn": game.turn,
                "fov": client._gather_fov(level),
                "explored": explored,
                "doors": client._gather_doors(level),
                "debug": client._gather_debug_data(
                    level, game.world),
            }
            _add_text(tar, f"exports/layer_state_{ts}.json",
                      _json.dumps(layer, indent=2))

            # 2b. Hatch polygon debug snapshot.
            hatch = {
                "timestamp": datetime.now().isoformat(),
                "turn": game.turn,
                **client._gather_hatch_debug(level),
            }
            _add_text(tar, f"exports/hatch_debug_{ts}.json",
                      _json.dumps(hatch, indent=2))

        # 3. Autosave
        if session.save_dir:
            autosave = session.save_dir / "autosave.nhc"
            if autosave.exists():
                tar.add(str(autosave), arcname="autosave.nhc")

        # 4. Game log
        log_file = Path(log_path) if log_path else None
        if log_file and log_file.exists():
            tar.add(str(log_file), arcname="nhc.log")

        # 5. Generation params (standalone for easy access)
        if gen_params:
            _add_text(
                tar,
                f"exports/generation_params_{ts}.json",
                _json.dumps(gen_params, indent=2),
            )

        # 6. Layer PNGs (uploaded by the client before bundle
        # download). Each value is a data:image/png;base64 URI.
        import base64
        layer_pngs = getattr(session, "layer_pngs", {})
        for name, data_uri in layer_pngs.items():
            try:
                # Strip the data:image/png;base64, prefix.
                _, encoded = data_uri.split(",", 1)
                png_bytes = base64.b64decode(encoded)
                info = tarfile.TarInfo(
                    name=f"layers/{name}.png",
                )
                info.size = len(png_bytes)
                tar.addfile(info, io.BytesIO(png_bytes))
            except Exception:
                pass  # skip malformed entries
        # Clear after bundling so they don't accumulate.
        session.layer_pngs = {}

        # 7. Browser console log (captured by the client-side
        # interceptor and uploaded with layer PNGs).
        console_log = getattr(session, "console_log", "")
        if console_log:
            _add_text(tar, "console.log", console_log)
            session.console_log = ""

        # 8. Extra entries supplied by the caller (e.g. the tester
        # report's ``report.txt``). Added last so bundle builders
        # can override any standard entry if they need to.
        for arcname, text in extra_entries:
            _add_text(tar, arcname, text)

    return buf.getvalue()
