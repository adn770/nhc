"""Token-based authentication for the web server.

Two auth layers:
- **Admin**: master token + LAN-only, for ``/admin`` routes
- **Player**: per-player token validated against a
  :class:`~nhc.web.registry.PlayerRegistry`, for game routes

Tokens can be provided via:
- Cookie: ``nhc_token`` (player) or ``nhc_admin_token`` (admin)
- Header: ``Authorization: Bearer <token>``
- Query param: ``?token=<token>``
"""

from __future__ import annotations

import hashlib
import ipaddress
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
    """Extract token from request (cookie, header, or query param)."""
    token = request.cookies.get(cookie_name)
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.args.get("token")


def _is_lan(ip: str | None) -> bool:
    """True if *ip* is a private/loopback address."""
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


# ── Legacy decorator (kept for existing tests) ─────────────

def require_auth(valid_hashes: set[str]):
    """Decorator that rejects requests without a valid token."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = _extract_token()
            if not token:
                return jsonify({"error": "authentication required"}), 401
            if hash_token(token) not in valid_hashes:
                return jsonify({"error": "invalid token"}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Admin decorator ─────────────────────────────────────────

def require_admin(admin_hash: str):
    """Decorator: admin token + LAN IP required."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not _is_lan(request.remote_addr):
                return jsonify({"error": "LAN access only"}), 403
            token = _extract_token(cookie_name="nhc_admin_token")
            if not token:
                return jsonify({"error": "authentication required"}), 401
            if hash_token(token) != admin_hash:
                return jsonify({"error": "invalid token"}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Player decorator ────────────────────────────────────────

def require_player(registry: "PlayerRegistry"):
    """Decorator: valid (non-revoked) player token required.

    On success, sets ``flask.g.player_id``.
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
            g.player_id = registry.player_id_for_hash(h)
            return f(*args, **kwargs)
        return wrapped
    return decorator
