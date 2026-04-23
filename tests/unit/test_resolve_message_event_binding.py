"""Regression: ``Game._resolve`` must not shadow ``MessageEvent``.

The teleporter-pad hook (commit d88bad8) introduced a local
``from nhc.core.events import MessageEvent`` inside a branch of
``_resolve``. Python's compile-time scope analysis promotes the
name to a function-local everywhere in the body — so the earlier
use (``isinstance(event, MessageEvent)`` on the event-tagging
loop) raises ``UnboundLocalError`` the first time the resolver
sees an event-producing action (e.g. opening a door). This test
pins the invariant statically so the regression can't come back.
"""

from __future__ import annotations

from nhc.core.game import Game


def test_resolve_does_not_shadow_message_event():
    varnames = Game._resolve.__code__.co_varnames
    assert "MessageEvent" not in varnames, (
        "_resolve has a local 'MessageEvent' binding — a "
        "conditional import is shadowing the module-level import "
        "and will trigger UnboundLocalError at runtime."
    )
