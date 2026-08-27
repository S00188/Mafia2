# Mafia Telegram Mini App

A group social-deduction game: the bot lives in a Telegram group, one
`/start` posts a join button, everyone taps it, and the game itself runs
as a Telegram Mini App (WebSocket-driven, server-authoritative) styled as
a cinematic film-noir poster.

Three pieces, three processes:

```
mafia-game/
├── backend/     FastAPI game engine + REST/WebSocket API + the Mini App itself
│   └── app/static/   index.html + app.js — served by the backend, no separate host needed
├── bot/         aiogram 3 bot — posts the join button, nothing else
```

## How the pieces fit together

1. **Bot** (`bot/bot.py`): admin adds the bot to a group. Anyone runs
   `/start` in that group. The bot posts one button — a Telegram `web_app`
   button whose URL is the backend's address plus `?chat_id=<the group>`.
2. **Mini App** (`backend/app/static/`): tapping the button opens this.
   It reads Telegram's signed `initData` for identity and the `chat_id`
   from its own URL, logs in, and calls `POST /games/for-chat`.
3. **Backend** (`backend/app/`): `for-chat` is the *only* way a match gets
   created — the first tap creates it and that player becomes host; every
   tap after joins the same match. No one ever calls a generic "create
   game" endpoint. From there the WebSocket (`/ws/games/{id}`) carries
   every state update: lobby → role reveal → night → day → vote → result
   → next night, or game over. The host can start once 6+ have joined;
   at 25 it starts itself.

There is no database the frontend talks to directly and no separate
static-file host to configure — `GET /` on the backend serves the app,
`/static/app.js` serves its script, and everything else is the API.

## Running it locally

```bash
# 1) backend
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN, SESSION_SECRET
uvicorn app.main:app --reload --port 8000

# 2) bot (separate terminal)
cd bot
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...        # same token as the backend
export WEBAPP_URL=https://<a public HTTPS URL for the backend>
python bot.py
```

Telegram requires the Mini App URL to be **public HTTPS** — `localhost`
will not work from a real Telegram client. For local development, tunnel
port 8000 (ngrok, Cloudflare Tunnel, etc.) and put that URL in
`WEBAPP_URL`. In production, both processes point at wherever the backend
is actually deployed (Fly.io, a VPS, ...).

## Deploying free: Render + Neon

`render.yaml` at the repo root is a Render Blueprint for exactly one free
resource: a `plan: free` web service. Two things make that possible for
the *whole* stack, not just the backend:

- **No Render Postgres.** Render's free Postgres instances expire after
  30 days; there's deliberately no `databases:` block in `render.yaml`.
  Instead, `DATABASE_URL` points at an external
  [Neon](https://neon.tech) Postgres project — free tier, doesn't expire.
  Paste in Neon's connection string exactly as their dashboard gives it
  (`sslmode=require&channel_binding=require` included); `asyncpg` doesn't
  understand those libpq-style params and would crash on them as-is, so
  `backend/app/database.py` strips and translates them itself. Use
  Neon's **direct** connection string (no `-pooler` in the hostname) —
  simpler than dealing with PgBouncer's prepared-statement caveats for an
  always-on service like this one (the backend sets
  `statement_cache_size=0` defensively either way, so the pooled one
  would also work if that's what you'd rather use).
- **No separate worker for the bot.** Render's free tier has no free
  instance type for background workers — only web services, static
  sites, Postgres, and Key Value. `bot/bot.py`'s long-polling process
  needs a worker, so instead `backend/app/telegram_bot.py` runs the same
  two handlers over a **webhook** — a route on the *same* free web
  service, registered automatically with Telegram on startup. Set
  `TELEGRAM_WEBHOOK_ENABLED=true` (already set in `render.yaml`) for this
  mode; leave it `false` (the default) anywhere still running
  `bot/bot.py` as its own process (a VPS, Fly.io) — a bot token can only
  be in webhook or polling mode at a time, so pick one deployment target.

Setup: create a Neon project and copy its connection string, get a bot
token from @BotFather, find your own Telegram ID via @userinfobot for
`ADMIN_TELEGRAM_IDS`, then in the Render dashboard: **New → Blueprint →**
pick this repo **→ Apply**. Render prompts for the `sync: false`
variables (`TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `ADMIN_TELEGRAM_IDS`)
during that flow; `SESSION_SECRET` and `TELEGRAM_WEBHOOK_SECRET` are
auto-generated. Full detail is commented in `render.yaml` itself.

The one real tradeoff: a free web service spins down after 15 minutes of
no traffic and takes a few seconds to wake back up on the next request or
Telegram update. Fine for a friend-group game; upgrade the instance type
later if that cold start ever matters.

## Tests

```bash
cd backend && pytest -q
```

121 tests: the full game engine (roles, night resolution, voting, win
conditions for all three factions), Telegram `initData` verification,
Telegram group-membership enforcement on `for-chat`, the automatic
night/day/vote/results phase cycle, the bot-owner global admin panel
(both the `GameEngine` `host_id=None` "system caller" path and the REST
layer's `require_bot_admin` gate), the Neon/asyncpg connection-string
handling and the webhook-mode bot integration (including that importing
it never constructs a real, token-validated `Bot`), and full-stack smoke
tests that exercise the real HTTP + WebSocket path end-to-end (join over
REST → connect the socket → start the game → confirm a role was dealt) —
this last kind of test is what caught a real crash (`get_player_view`
throwing on the very first WebSocket message, before any role was
assigned) that the earlier engine-only tests couldn't see.

## What's genuinely done vs. what's still a v1 simplification

**Solid:**
- All 20 roles, all 20 player-count compositions (6–25), night resolution,
  voting, win conditions — unchanged from Phase 1, still 100% test-covered.
- The group-bound match model described above (`for-chat`, auto-start at
  25) — this didn't exist until this pass; earlier builds only had a
  generic "create game" flow that didn't match the product.
- The Mini App is now wired to real data end to end: lobby roster, role
  reveal, night action prompts (built generically from
  `night_action_type`/`night_action_needs_target` so the frontend never
  hardcodes per-role logic), voting, outcome, and win screens all reflect
  actual server state, not placeholders.
- **In-app discussion chat** (spec sections 11/32): real-time, scoped to
  one game, server-authoritative — alive-only, phase-gated to discussion,
  blocked for a Silencer's target that day, dead players spectate but
  can't send. The Telegram group is never involved.
- **Final role reveal + personal statistics** at game over (spec section
  22): every player's role becomes visible to everyone once the game
  ends, and each player sees their own kills/investigations/protections/
  votes-cast tally.

**Fixed since the last pass:**
- `chat_id` is now checked against Telegram's own `getChatMember` (see
  `app/services/telegram_bot_api.py`) before `for-chat` creates or joins a
  match — a caller Telegram doesn't confirm as a current member of that
  group is rejected with 403. Fails closed on any error talking to
  Telegram, including a bad/missing bot token.
- The night → day → discussion → voting → results → next night loop now
  fully drives itself off each phase's own server timer
  (`advance_to_voting_if_ready` / `start_next_night_if_ready`, called by
  the same background ticker that already force-resolved night and
  voting) — a WebApp where nobody taps anything no longer gets stuck once
  the day or the post-vote pause runs out.
- Mayor-reveal and Gunner-shoot now have their own buttons on the day
  screen (ammo/charge indicator included for the Gunner), driven off the
  same `day_action_type` field the backend was already sending. Both are
  now also enforced server-side as day-only actions (a raw message can no
  longer trigger them at night or during voting).
- Reopening the Mini App (Telegram closed and relaunched, a refresh, a
  dropped connection) now rejoins automatically instead of requiring a
  fresh tap of "Kirish", as long as the group's `chat_id` is still in the
  URL.
- A **global admin panel for the bot owner** (a new "Admin" tab, visible
  only to Telegram user IDs listed in `ADMIN_TELEGRAM_IDS` — see
  `.env.example` — not tied to being any single match's host, and usable
  without ever having joined the game being managed): browse every
  currently active match across every Telegram group, see real
  roles/alive-status for every player (the one place in the app allowed to
  show that), tune `GameSettings` before a match starts, force the current
  phase to resolve early, add +30s to the running phase, remove a player,
  or terminate a stuck match outright. All served over REST
  (`app/api/routes_admin.py`), gated by `require_bot_admin`, and backed by
  the same `GameEngine` methods a per-match host's own WebSocket messages
  already used — those now accept `host_id=None` to mean "an
  already-authorized system caller, not necessarily a player in this
  game" (see `_require_host_or_system`).
- **Free deployment on Render + Neon** (see "Deploying free" above):
  `render.yaml` for a single free web service, no Render Postgres (data
  goes to Neon instead — its free tier doesn't expire like Render's does),
  and the bot's own logic running as a webhook inside that same service
  (`app/telegram_bot.py`) since Render's free tier has no free
  background-worker instance. `bot/bot.py`'s polling-mode process is
  untouched and still the right choice for a VPS or Fly.io deployment.

**Known v1 simplifications, not bugs:**
- Host = whoever's `for-chat` call created the match, not "a Telegram
  group admin" specifically. This matches how the spec actually reads
  ("the admin *or* whoever started it"), but if you want it restricted to
  real Telegram admins, that's a further `getChatMember` role check away.
- Neutral-faction wins (Survivor/Jester/Serial Killer/Arsonist) reuse the
  Mafia win screen's artwork recolored, since only Town/Mafia have unique
  poster art from the design pass.
- The server's phase list (`lobby`, `role_assignment`, `night`,
  `day_discussion`, `voting`, `vote_results`, `game_over`) is a
  deliberately collapsed version of a more granular spec (which also
  names `night_resolution`, `morning_result`, `vote_resolution`,
  `elimination` as their own states): those steps still happen, just as
  instantaneous server-side transitions rather than states a client can
  be paused in or reconnect into mid-step. The one place this could
  matter — a player reconnecting *exactly* between night-end and the
  death announcement — falls back to just showing the day screen with no
  announcement, rather than losing or corrupting anything.
- In-memory game registry (per the original Phase 1 note): a backend
  restart mid-game loses live matches. Finished games are persisted for
  history; live-match persistence is future work.
