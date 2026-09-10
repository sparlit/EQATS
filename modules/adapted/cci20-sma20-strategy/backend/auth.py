from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
Cognito JWT authentication dependency for FastAPI.

Flow
────
1. Angular does PKCE login → Cognito Hosted UI → receives access_token (JWT).
2. Angular sends:  Authorization: Bearer <access_token>
3. FastAPI (this module) validates signature against Cognito JWKS public keys.
4. On success, auto-creates a User row for first-time logins (upsert pattern).
5. Returns the User ORM instance — downstream handlers can use it freely.

Environment variables
  COGNITO_REGION       e.g. ap-southeast-1
  COGNITO_USER_POOL_ID e.g. ap-southeast-1_XXXXXXXX
  COGNITO_APP_CLIENT_ID  e.g. 5xxxxxxxxxxxxxxxxxxxx
"""

import logging
import os
from typing import TYPE_CHECKING, Optional

import httpx
from db.connection import get_db
from db.models import User
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

COGNITO_REGION = os.environ.get("COGNITO_REGION", "ap-southeast-1")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")

JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"

# Cached per Lambda warm instance — avoids a network call on every request
_jwks_keys: list | None = None

security = HTTPBearer(auto_error=True)


async def _fetch_jwks() -> list:
    global _jwks_keys
    if _jwks_keys is None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            _jwks_keys = resp.json().get("keys", [])
        logger.info("Fetched %d Cognito JWKS keys", len(_jwks_keys))
    return _jwks_keys


def _find_key(kid: str, keys: list) -> dict | None:
    return next((k for k in keys if k.get("kid") == kid), None)


_401 = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency.
    Validates Cognito JWT and returns (or auto-creates) the User ORM row.
    """
    token = credentials.credentials
    try:
        # 1. Decode header (unverified) to get key id
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise _401

        # 2. Find matching public key
        keys = await _fetch_jwks()
        key = _find_key(kid, keys)
        if not key:
            # Key may have been rotated — flush cache and retry once
            global _jwks_keys
            _jwks_keys = None
            keys = await _fetch_jwks()
            key = _find_key(kid, keys)
        if not key:
            raise _401

        # 3. Verify signature, expiry, and audience
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=COGNITO_APP_CLIENT_ID or None,
            options={"verify_exp": True, "verify_aud": bool(COGNITO_APP_CLIENT_ID)},
        )
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise _401 from exc

    cognito_sub: str = payload.get("sub", "")
    email: str = payload.get("email", "") or payload.get("cognito:username", "")

    if not cognito_sub:
        raise _401

    # 4. Get or create User row (upsert on first login)
    result = await db.execute(select(User).where(User.cognito_sub == cognito_sub))
    user = result.scalar_one_or_none()
    if not user:
        user = User(cognito_sub=cognito_sub, email=email)
        db.add(user)
        await db.flush()
        logger.info("Auto-created user cognito_sub=%s", cognito_sub)

    return user


ADMIN_COGNITO_SUB = os.environ.get("ADMIN_COGNITO_SUB", "scanner-admin")


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    FastAPI dependency for routes that require Admin privileges.
    Verifies that the current user's cognito_sub matches the ADMIN_COGNITO_SUB.
    """
    if current_user.cognito_sub != ADMIN_COGNITO_SUB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user
