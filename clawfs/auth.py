"""Bearer-token auth for write endpoints."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException, status


def load_tokens() -> set[str]:
    raw = os.environ.get("CLAWFS_API_TOKENS", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def require_auth(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: enforce `Authorization: Bearer <token>`.

    If no tokens are configured, all requests are denied (fail-closed).
    """
    tokens = load_tokens()
    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth not configured (CLAWFS_API_TOKENS empty)",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if token not in tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def maybe_require_auth(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """Conditional auth for read endpoints, gated by `CLAWFS_REQUIRE_AUTH_READ`."""
    if os.environ.get("CLAWFS_REQUIRE_AUTH_READ", "").lower() in ("1", "true", "yes"):
        return require_auth(authorization)
    return None
