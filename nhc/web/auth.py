"""Token-based authentication for the web server.

Two auth layers:
- **Admin**: master token, for ``/admin`` routes.
- **Player**: per-player token validated against a
  :class:`~nhc.web.registry.PlayerRegistry`, for game routes.

Tokens can be provided via:
- Cookie: ``nhc_token`` (player) or ``nhc_admin_token`` (admin)
- Header: ``Authorization: Bearer <token>``
- Query param: ``?token=<token>``
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import wraps
from typing import TYPE_CHECKING

from flask import g, jsonify, request

if TYPE_CHECKING:
    from nhc.web.registry import PlayerRegistry


def generate_token() -> str:
    """Generate a random access token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage (avoid storing plaintext)."""
    return hashlib.sha256(token.encode()).hexdigest()


def _extract_token(cookie_name: str = "nhc_token") -> str | None:
    """Extract token from request.

    Priority: query param > cookie > Authorization header.
    Query param takes precedence so that a fresh link overrides
    any stale cookie from a previous session.
    """
    # Query parameter (highest priority — fresh link click)
    token = request.args.get("token")
    if token:
        return token
    # Cookie
    token = request.cookies.get(cookie_name)
    if token:
        return token
    # Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


# ── Legacy decorator (kept for existing tests) ─────────────

def require_auth(valid_hashes: set[str]):
    """Decorator that rejects requests without a valid token."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = _extract_token()
            if not token:
                return jsonify({"error": "authentication required"}), 401
            candidate = hash_token(token)
            # Constant-time comparison against each valid hash.
            # ``in`` on a set is O(1) but compares via ``__eq__``,
            # which on CPython short-circuits on first mismatch —
            # hygienic preference is ``compare_digest``.
            if not any(hmac.compare_digest(candidate, h)
                       for h in valid_hashes):
                return jsonify({"error": "invalid token"}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Admin decorator ─────────────────────────────────────────

def require_admin(admin_hash: str):
    """Decorator: admin token required for ``/admin`` routes.

    Access is gated by the admin token alone; there is no client-IP
    restriction.
    """

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = _extract_token(cookie_name="nhc_admin_token")
            if not token:
                return jsonify({"error": "authentication required"}), 401
            if not hmac.compare_digest(hash_token(token), admin_hash):
                return jsonify({"error": "invalid token"}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Player decorator ────────────────────────────────────────

def require_player(registry: "PlayerRegistry"):
    """Decorator: valid (non-revoked) player token required.

    On success, sets ``flask.g.player_id`` and bumps the player's
    ``last_seen`` timestamp so the admin panel can report recent
    activity.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = _extract_token()
            if not token:
                return jsonify({"error": "authentication required"}), 401
            h = hash_token(token)
            if not registry.is_valid_token_hash(h):
                return jsonify({"error": "invalid or revoked token"}), 403
            pid = registry.player_id_for_hash(h)
            g.player_id = pid
            registry.touch(pid)
            return f(*args, **kwargs)
        return wrapped
    return decorator
