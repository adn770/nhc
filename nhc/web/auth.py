"""Token-based authentication for the web server.

Two auth layers:
- **Admin**: master token + LAN allowlist, for ``/admin`` routes.
  The allowlist is an explicit list of :class:`ipaddress` networks,
  NOT ``ipaddress.is_private()``. ``is_private()`` treats loopback
  and Docker bridge ranges as "LAN", which silently bypasses the
  guard when the app sits behind a reverse proxy on localhost.
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
import ipaddress
import secrets
from functools import wraps
from typing import TYPE_CHECKING, Sequence, Union

from flask import g, jsonify, request

if TYPE_CHECKING:
    from nhc.web.registry import PlayerRegistry


IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


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


def _ip_in_networks(
    ip: str | None, networks: Sequence[IPNetwork],
) -> bool:
    """Return True if *ip* parses and falls inside any of *networks*.

    Fails closed on any error (invalid IP, empty list, None).
    """
    if not ip or not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in networks)


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

def require_admin(
    admin_hash: str,
    lan_networks: Sequence[IPNetwork] | None = None,
):
    """Decorator: admin token + client-IP-on-allowlist.

    *lan_networks* is an explicit allowlist. If empty or ``None``,
    the LAN check fails closed — every admin request is denied.
    The caller must supply the configured LAN CIDRs; this function
    does not fall back to ``ipaddress.is_private``, which would
    re-introduce the loopback / Docker-bridge bypass.
    """
    networks = tuple(lan_networks or ())

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not _ip_in_networks(request.remote_addr, networks):
                return jsonify(
                    {"error": "admin only available from LAN"}
                ), 403
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
