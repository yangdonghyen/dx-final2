import logging

from fastapi import WebSocket

logger = logging.getLogger("app.youtube_bridge")


class YouTubeBridgeManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)
        logger.info("youtube_bridge WS_CONNECTED clients=%s", len(self.connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)
            logger.info("youtube_bridge WS_DISCONNECTED clients=%s", len(self.connections))

    async def broadcast(self, message: dict) -> int:
        """Send to every connected app; returns how many received it."""
        disconnected: list[WebSocket] = []

        for websocket in self.connections:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket)
        return len(self.connections)


youtube_bridge_manager = YouTubeBridgeManager()
