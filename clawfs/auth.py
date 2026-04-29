"""Bearer-token auth for write endpoints.

Accepts either:
  1. Tokens in the CLAWFS_API_TOKENS env CSV (legacy / single-tenant)
  2. Tokens registered to a Tenant row (multi-tenant, Sprint 4+)

A process-wide module-global :data:`tenant_token_check` is set by
:func:`clawfs.api.create_app` so this module doesn't have to import the DB
(would create an import cycle).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import Header, HTTPException, status

# Set by create_app() to a callable: token -> Optional[tenant_id]
tenant_token_check: Optional[Callable[[str], Optional[str]]] = None


def load_tokens() -> set[str]:
    raw = os.environ.get("CLAWFS_API_TOKENS", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def _is_valid(token: str) -> bool:
    if token in load_tokens():
        return True
    if tenant_token_check is not None and tenant_token_check(token) is not None:
        return True
    return False


def require_auth(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: enforce ``Authorization: Bearer <token>``.

    Accepts both env-CSV tokens and tenant-registered tokens. Fails closed
    when neither source has any tokens configured.
    """
    has_env = bool(load_tokens())
    has_db = tenant_token_check is not None
    if not has_env and not has_db:
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
    if not _is_valid(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def maybe_require_auth(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    if os.environ.get("CLAWFS_REQUIRE_AUTH_READ", "").lower() in ("1", "true", "yes"):
        return require_auth(authorization)
    return None
