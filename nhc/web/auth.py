"""Simple token-based authentication for the web server.

When auth is enabled, clients must provide a valid token via:
- Cookie: nhc_token=<token>
- Header: Authorization: Bearer <token>
- Query param: ?token=<token> (for WebSocket connections)
"""

from __future__ import annotations

import hashlib
import secrets
from functools import wraps

from flask import request, jsonify


def generate_token() -> str:
    """Generate a random access token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage (avoid storing plaintext)."""
    return hashlib.sha256(token.encode()).hexdigest()


def _extract_token() -> str | None:
    """Extract token from request (cookie, header, or query param)."""
    # Cookie
    token = request.cookies.get("nhc_token")
    if token:
        return token
    # Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Query parameter (for WebSocket upgrade requests)
    return request.args.get("token")


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
