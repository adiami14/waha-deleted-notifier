"""
Admin session-cookie auth for bot-notify-delete.

Accepts either:
  1. A valid signed session cookie (standalone direct access)
  2. X-Internal-Token header matching INTERNAL_TOKEN env var (management proxy)
"""

import os

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

from app.config import settings

_INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")


class AdminNotAuthenticated(Exception):
    """Raised when the session cookie is missing/invalid and no proxy token present."""


_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
COOKIE_NAME = "nd_admin_session"


def _serializer() -> URLSafeTimedSerializer:
    key = settings.secret_key.get_secret_value()
    return URLSafeTimedSerializer(key, salt="nd-admin-session")


def verify_password(plain: str) -> bool:
    return _pwd_ctx.verify(plain, settings.admin_password_hash)


def create_session_cookie(response, username: str) -> None:
    token = _serializer().dumps({"u": username})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME)


def _decode_token(token: str) -> str | None:
    try:
        data = _serializer().loads(token, max_age=settings.session_max_age_seconds)
        return data.get("u")
    except (SignatureExpired, BadSignature, Exception):
        return None


async def require_admin(request: Request) -> str:
    # Accept management proxy token (X-Internal-Token bypass)
    if _INTERNAL_TOKEN and request.headers.get("x-internal-token") == _INTERNAL_TOKEN:
        return "management"

    if not settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin panel not configured (ADMIN_PASSWORD_HASH is empty).",
        )
    token = request.cookies.get(COOKIE_NAME)
    if token:
        username = _decode_token(token)
        if username:
            return username
    raise AdminNotAuthenticated()
