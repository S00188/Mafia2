import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
import pytest

from app.services.telegram_auth import verify_init_data, TelegramAuthError

BOT_TOKEN = "123456:TEST-BOT-TOKEN"


def _build_init_data(user: dict, bot_token: str = BOT_TOKEN, auth_date: int | None = None) -> str:
    fields = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAEmastEAAAAACayxN0d5mNi",
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    correct_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = correct_hash
    return urlencode(fields)


def test_valid_init_data_is_accepted():
    init_data = _build_init_data({"id": 42, "first_name": "Samandar", "username": "sam"})
    user = verify_init_data(init_data, BOT_TOKEN)
    assert user.telegram_user_id == 42
    assert user.username == "sam"


def test_tampered_init_data_is_rejected():
    init_data = _build_init_data({"id": 42, "first_name": "Samandar"})
    tampered = init_data.replace("Samandar", "Attacker")
    with pytest.raises(TelegramAuthError):
        verify_init_data(tampered, BOT_TOKEN)


def test_wrong_bot_token_is_rejected():
    init_data = _build_init_data({"id": 42, "first_name": "Samandar"})
    with pytest.raises(TelegramAuthError):
        verify_init_data(init_data, "WRONG-TOKEN")


def test_expired_init_data_is_rejected():
    init_data = _build_init_data({"id": 42, "first_name": "Samandar"}, auth_date=int(time.time()) - 999999)
    with pytest.raises(TelegramAuthError):
        verify_init_data(init_data, BOT_TOKEN, max_age_seconds=86400)
