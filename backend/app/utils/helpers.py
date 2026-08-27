from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
from typing import Optional


class TokenError(ValueError):
    pass


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(telegram_user_id: int, secret: str, ttl_seconds: int) -> str:
    payload = {"uid": telegram_user_id, "exp": int(time.time()) + ttl_seconds}
    body = _b64e(json.dumps(payload).encode())
    sig = _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session_token(token: str, secret: str) -> int:
    try:
        body, sig = token.split(".")
    except ValueError:
        raise TokenError("Malformed token")
    expected_sig = _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected_sig, sig):
        raise TokenError("Bad token signature")
    payload = json.loads(_b64d(body))
    if payload["exp"] < time.time():
        raise TokenError("Token expired")
    return int(payload["uid"])


def new_game_code() -> str:
    """Short human-friendly game code, e.g. for '#1234' style lobby display."""
    import random
    return f"{random.randint(1000, 9999)}"
