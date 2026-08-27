from __future__ import annotations
import logging
from fastapi import WebSocket

logger = logging.getLogger("mafia.ws")


class ConnectionManager:
    def __init__(self) -> None:
        # game_id -> {player_id: WebSocket}
        self._rooms: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, game_id: str, player_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms.setdefault(game_id, {})[player_id] = ws

    def disconnect(self, game_id: str, player_id: str) -> None:
        room = self._rooms.get(game_id)
        if room:
            room.pop(player_id, None)
            if not room:
                self._rooms.pop(game_id, None)

    async def send_personal(self, game_id: str, player_id: str, message: dict) -> None:
        ws = self._rooms.get(game_id, {}).get(player_id)
        if ws:
            await ws.send_json(message)

    async def broadcast_state(self, game_id: str, engine) -> None:
        """Send every connected player their own authoritative, hidden-info-safe view."""
        room = self._rooms.get(game_id, {})
        for player_id, ws in list(room.items()):
            try:
                await ws.send_json({"type": "state", "state": engine.get_player_view(player_id)})
            except Exception:
                # A bug in get_player_view (or a genuinely dead socket) must
                # never vanish silently — it used to, and it hid a real
                # crash behind what looked like a client-side hang.
                logger.exception("broadcast_state failed for game=%s player=%s", game_id, player_id)
                self.disconnect(game_id, player_id)


manager = ConnectionManager()
