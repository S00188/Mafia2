from __future__ import annotations
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.utils.helpers import verify_session_token, TokenError
from app.services.game_service import registry, persist_finished_game
from app.game_engine.engine import EngineError
from app.game_engine.state import Phase
from app.websocket.manager import manager

router = APIRouter()


@router.websocket("/ws/games/{game_id}")
async def game_websocket(websocket: WebSocket, game_id: str, token: str = Query(...)):
    try:
        telegram_user_id = verify_session_token(token, settings.session_secret)
    except TokenError:
        await websocket.close(code=4401)
        return

    try:
        engine = registry.get(game_id)
    except KeyError:
        await websocket.close(code=4404)
        return

    player_id = engine.find_player_id(telegram_user_id)
    if not player_id:
        await websocket.close(code=4403)
        return

    await manager.connect(game_id, player_id, websocket)
    engine.state.players[player_id].connected = True
    await manager.broadcast_state(game_id, engine)

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle_message(game_id, engine, player_id, msg)
            await manager.broadcast_state(game_id, engine)
            if engine.state.phase == Phase.GAME_OVER:
                async with AsyncSessionLocal() as session:
                    await persist_finished_game(session, engine)
    except WebSocketDisconnect:
        engine.state.players[player_id].connected = False
        manager.disconnect(game_id, player_id)
        await manager.broadcast_state(game_id, engine)


async def _handle_message(game_id: str, engine, player_id: str, msg: dict) -> None:
    msg_type = msg.get("type")
    try:
        if msg_type == "night_action":
            engine.submit_night_action(player_id, msg.get("target_id"))
            engine.resolve_night_if_ready()
        elif msg_type == "advance_to_voting":
            engine.advance_to_voting()
        elif msg_type == "vote":
            engine.submit_vote(player_id, msg.get("target_id"))
            engine.resolve_voting_if_ready()
        elif msg_type == "start_next_night":
            engine.start_next_night()
        elif msg_type == "reveal_mayor":
            engine.reveal_mayor(player_id)
        elif msg_type == "gunner_shoot":
            engine.gunner_shoot(player_id, msg["target_id"])
        elif msg_type == "chat_message":
            engine.send_chat_message(player_id, msg.get("text", ""))
        elif msg_type == "start_game":
            engine.start_game(player_id)
        elif msg_type == "admin_update_settings":
            engine.update_settings(player_id, msg.get("settings") or {})
        elif msg_type == "admin_force_advance":
            engine.force_advance_phase(player_id)
        elif msg_type == "admin_extend_timer":
            engine.extend_current_phase(player_id, msg.get("seconds", 30))
        elif msg_type == "admin_remove_player":
            engine.admin_remove_player(player_id, msg.get("target_id"))
        else:
            await manager.send_personal(game_id, player_id, {"type": "error", "message": "Unknown action"})
    except EngineError as e:
        await manager.send_personal(game_id, player_id, {"type": "error", "message": str(e)})


async def phase_ticker() -> None:
    """Runs forever in the background: force-resolves any phase whose
    server-side timer has expired, even if not every player acted.

    This is what makes the whole night -> day -> discussion -> voting ->
    results -> next night loop keep going on its own: every phase's end is
    a real server timestamp (see TimerManager), and this loop is the thing
    that actually acts on it once it passes, for every phase that has a
    timer — not just night and voting."""
    while True:
        for engine in registry.all_engines():
            game_id = engine.state.game_id
            changed = False
            if engine.state.phase == Phase.NIGHT and engine.resolve_night_if_ready():
                changed = True
            elif engine.state.phase == Phase.VOTING and engine.resolve_voting_if_ready():
                changed = True
            elif engine.state.phase == Phase.DAY_DISCUSSION and engine.advance_to_voting_if_ready():
                changed = True
            elif engine.state.phase == Phase.VOTE_RESULTS and engine.start_next_night_if_ready():
                changed = True
            if changed:
                await manager.broadcast_state(game_id, engine)
                if engine.state.phase == Phase.GAME_OVER:
                    async with AsyncSessionLocal() as session:
                        await persist_finished_game(session, engine)
        await asyncio.sleep(1)
