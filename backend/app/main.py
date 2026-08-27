import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.api.routes_auth import router as auth_router
from app.api.routes_game import router as game_router
from app.api.routes_admin import router as admin_router
from app.websocket.handlers import router as ws_router, phase_ticker
from app.telegram_bot import router as bot_router, register_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mafia")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    ticker_task = asyncio.create_task(phase_ticker())
    if settings.telegram_webhook_enabled:
        # Only touches the Telegram API (and only constructs a real Bot,
        # which validates its token) when explicitly turned on — see
        # app/telegram_bot.py for why that matters for tests and for
        # deployments that run bot/bot.py's polling process instead.
        await register_webhook()
    yield
    ticker_task.cancel()


app = FastAPI(title="Mafia Mini App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to clients (spec section 29).
    logger.exception("Unhandled error on %s", request.url)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})


app.include_router(auth_router)
app.include_router(game_router)
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(bot_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# The Telegram Mini App itself. Everything under /static/* (app.js, and any
# future split-out assets) is served as plain files; "/" serves the shell
# so opening the bot's web_app URL with no path works with zero server-side
# templating — app.js does the rest once the browser has it.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_app():
    return FileResponse(STATIC_DIR / "index.html")

