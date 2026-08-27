"""
Verifies Telegram Mini App `initData` server-side, per Telegram's WebApp
auth scheme. Never trust a user_id sent directly by the frontend — this is
the only legitimate way to know who is really talking to the backend.

Algorithm (Telegram spec):
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  data_check_string = all fields except 'hash', sorted "key=value", joined by \n
  expected_hash = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()
  valid if expected_hash == received hash, and auth_date is recent.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl
from dataclasses import dataclass
from typing import Optional


class TelegramAuthError(ValueError):
    pass


@dataclass
class TelegramUser:
    telegram_user_id: int
    first_name: str
    last_name: Optional[str]
    username: Optional[str]
    photo_url: Optional[str]


def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> TelegramUser:
    if not init_data:
        raise TelegramAuthError("Missing initData")

    pairs = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("initData missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthError("Invalid initData signature")

    auth_date = int(pairs.get("auth_date", "0"))
    if max_age_seconds and time.time() - auth_date > max_age_seconds:
        raise TelegramAuthError("initData has expired")

    user_json = pairs.get("user")
    if not user_json:
        raise TelegramAuthError("initData missing user")
    user = json.loads(user_json)

    return TelegramUser(
        telegram_user_id=int(user["id"]),
        first_name=user.get("first_name", ""),
        last_name=user.get("last_name"),
        username=user.get("username"),
        photo_url=user.get("photo_url"),
    )
