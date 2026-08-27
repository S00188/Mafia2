# Mafia Mini App — Backend (Phase 1)

Server-authoritative game engine + FastAPI + WebSocket backend for a
Telegram Mini App Mafia game. **This is Phase 1 of the full spec** — see
"What's built vs. what's next" at the bottom before you assume it's the
whole app.

## What actually works right now

- **Full game engine**, independent of any web framework, covering all 20
  roles across Mafia/Town/Neutral: role assignment from a hand-tuned,
  documented composition table for every player count from 6 to 25,
  night-action
  validation, night resolution (kills, protection, framing, silencing,
  tracking, watching, veteran alerts, arsonist douse/ignite, gunner),
  investigation results, day voting (weights, ties, self-vote rules),
  elimination, and win-condition checks for all three factions.
- **47 automated tests**, all passing, exercising the engine directly
  (no HTTP/WebSocket involved) plus a full HTTP smoke test that creates a
  lobby, joins 8 players, starts the game, and confirms roles were dealt
  and hidden correctly.
- **Telegram `initData` verification** implemented from Telegram's HMAC
  spec (not a stub) — tested against valid, tampered, wrong-bot-token, and
  expired payloads.
- **Server-authoritative timers**: every phase has `phase_start`/`phase_end`
  on the server; a background ticker force-resolves night/voting if the
  timer runs out even if players didn't act.
- **WebSocket real-time layer** with per-player hidden-info state (nobody
  ever receives another living player's role, mafia teammates are only
  sent to mafia, etc.) and reconnection: a client can drop and reconnect
  and gets the exact same authoritative state back — no re-rolled roles,
  no duplicated actions.
- **REST fallback** (`GET /games/{id}/state`) for reconnecting before the
  WebSocket handshake completes, and endpoints for create/join/start/kick.
- **Database models** for User, Game, GamePlayer, Role, GameAction, Vote,
  GameEvent, GameSettings, GameHistory — wired up so a finished game is
  persisted with per-player results for stats/history screens.

## Design decisions worth knowing about

- **Live game state lives in memory** (one `GameEngine` per running game,
  held by `GameRegistry`), not re-read from Postgres on every action —
  this is what makes it fast and simple, and it's exactly what makes
  reconnection work (the player rejoins the same running process and gets
  the same object back). The trade-off: if the server process restarts
  mid-game, in-flight games are lost. Hardening that (e.g. periodic state
  snapshots to `GameEvent`/Redis) is the natural next step before this
  goes to real production traffic — the DB schema is already shaped for it.
- **Medium** is intentionally simplified to "opens a seance channel with a
  dead player" rather than a full two-way chat bridge — that's a frontend
  feature (a dead-chat UI) layered on top of this flag, not an engine change.
- **Gunner** is a day action with 2 bullets rather than a night action, so
  it doesn't collide with the mafia-kill/investigation night structure.
- Composition table reasoning is documented at the top of
  `app/game_engine/compositions.py`.

## Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN and SESSION_SECRET
```

### Run tests

```bash
pytest -q
```

### Run the dev server

```bash
uvicorn app.main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/health`

### Telegram Bot setup

The bot process lives in `../bot/` (separate from this backend) — see the
top-level `README.md` for how the two run together. In short:

1. Talk to [@BotFather](https://t.me/BotFather), `/newbot`, copy the token
   into both `backend/.env` and `bot/.env`.
2. Set `bot`'s `WEBAPP_URL` to wherever this backend is publicly reachable
   over HTTPS (Telegram refuses plain HTTP and refuses `localhost`; tunnel
   with ngrok/Cloudflare Tunnel for local dev).
3. Run both processes. `/start` in a group is the only way a match gets
   created — there's no admin panel or setup step beyond that.

### Production deployment (outline)

- Run `uvicorn`/`gunicorn -k uvicorn.workers.UvicornWorker` behind a
  reverse proxy (nginx / Caddy) that terminates TLS.
- Point `DATABASE_URL` at real Postgres.
- Set `CORS_ORIGINS` to your actual frontend origin(s), not `*`.
- Put the WebSocket route behind the same TLS-terminated proxy
  (`wss://yourdomain/ws/games/{id}`).

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/telegram` | Verify `initData`, return session token |
| POST | `/games/for-chat` | **The real entry point.** Get-or-create the one match bound to a Telegram `chat_id`, and join the caller into it |
| POST | `/games` | Create a lobby directly (host) — used by tests; the product itself never calls this |
| POST | `/games/{id}/join` | Join a lobby by game code |
| POST | `/games/{id}/start` | Host starts the game |
| GET | `/games/{id}/state` | Reconnect fallback: full hidden-info-safe state |
| POST | `/games/{id}/kick/{player_id}` | Host kicks a lobby player |
| WS | `/ws/games/{id}?token=...` | Real-time gameplay |
| GET | `/` , `/static/*` | The Mini App itself (`app/static/index.html` + `app.js`) |

WebSocket message types (client → server): `night_action`, `vote`,
`advance_to_voting`, `start_next_night`, `reveal_mayor`, `gunner_shoot`,
`start_game`. Server → client: `{"type": "state", "state": <player view>}`
or `{"type": "error", "message": "..."}`.

## What's built vs. what's next

**Built:** game engine (all 20 roles, full 6–25 composition table),
database layer, Telegram auth, REST + WebSocket API, the group-bound
`for-chat` match model with auto-start at 25, server-authoritative timers,
reconnection, the Mini App itself wired to real state end-to-end
(`app/static/`), the bot that posts the join button (`../bot/`), and 47
passing tests including full-stack WebSocket smoke tests. See the
top-level `README.md` for the honest list of v1 simplifications
(chat-membership isn't independently verified server-side yet, neutral
wins reuse the Mafia win screen's art, Mayor-reveal/Gunner-shoot have no
button in the UI yet, etc.) — none of it is hidden there, worth reading
before deploying beyond a friend group.

**Not built yet:**
- Custom game mode configuration UI (the engine already accepts arbitrary
  `GameSettings`; there's just no screen to edit them yet).
- Rate limiting and production-grade WebSocket auth hardening.
- Alembic migration files (currently `init_db()` uses `create_all`, fine
  for early development, not for schema evolution in production).
- Crash-recovery persistence for in-flight games (see design note above).
