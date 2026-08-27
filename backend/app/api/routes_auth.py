from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.config import settings
from app.database import get_session
from app.i18n import get_user_language
from app.services.telegram_auth import verify_init_data, TelegramAuthError
from app.services.game_service import get_or_create_user
from app.utils.helpers import create_session_token, verify_session_token, TokenError

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramLoginRequest(BaseModel):
    init_data: str


class TelegramLoginResponse(BaseModel):
    session_token: str
    telegram_user_id: int
    display_name: str
    photo_url: str | None = None
    # Lets the WebApp know, right at login and without a second round trip,
    # whether to show the bot-owner-only "Admin" tab. The real gate is on
    # every /admin/* endpoint (require_bot_admin below) — this flag is a
    # display convenience, not the authorization itself.
    is_bot_admin: bool = False
    # The user's preferred language (see app/i18n.py) — shared with the bot,
    # so switching it from the bot's own menu is reflected here too.
    language: str = "uz"


@router.post("/telegram", response_model=TelegramLoginResponse)
async def login_with_telegram(body: TelegramLoginRequest, session: AsyncSession = Depends(get_session)):
    try:
        tg_user = verify_init_data(body.init_data, settings.telegram_bot_token)
    except TelegramAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user = await get_or_create_user(
        session, tg_user.telegram_user_id, tg_user.first_name,
        tg_user.last_name, tg_user.username, tg_user.photo_url,
    )
    token = create_session_token(tg_user.telegram_user_id, settings.session_secret,
                                  settings.session_ttl_seconds)
    display_name = tg_user.username or f"{tg_user.first_name} {tg_user.last_name or ''}".strip()
    language = await get_user_language(tg_user.telegram_user_id)
    return TelegramLoginResponse(session_token=token, telegram_user_id=tg_user.telegram_user_id,
                                  display_name=display_name, photo_url=tg_user.photo_url,
                                  is_bot_admin=tg_user.telegram_user_id in settings.admin_telegram_ids,
                                  language=language)


def require_telegram_id(authorization: str | None = Header(default=None)) -> int:
    """Dependency: pulls 'Bearer <session_token>' from the Authorization header
    and returns the verified telegram_user_id. Never trust a client-sent user_id."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing session token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_session_token(token, settings.session_secret)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))


def require_bot_admin(telegram_user_id: int = Depends(require_telegram_id)) -> int:
    """Dependency for /admin/* routes: a valid session isn't enough, the
    Telegram user behind it also has to be in settings.admin_telegram_ids
    — the bot owner (or whoever they've configured), not any particular
    match's host."""
    if telegram_user_id not in settings.admin_telegram_ids:
        raise HTTPException(status_code=403, detail="Siz bot admini emassiz")
    return telegram_user_id
