"""
EZ-NEXUS AI — Real-Time Notification Hub
WebSocket connection manager.  Broadcasts JSON events to all connected clients.
"""

import json
import logging
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class NotificationHub:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self):
        # Maps connection_id → WebSocket
        self._connections: Dict[str, WebSocket] = {}

    # ── Connection lifecycle ────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self._connections[client_id] = websocket
        logger.info("WebSocket connected: %s  (total: %d)", client_id, len(self._connections))

        # Greet the new client
        await self._send(websocket, {
            "type": "connected",
            "message": f"Connected to EZ-NEXUS AI notification hub. ID: {client_id}",
            "clients": len(self._connections),
        })

    def disconnect(self, client_id: str) -> None:
        self._connections.pop(client_id, None)
        logger.info("WebSocket disconnected: %s  (total: %d)", client_id, len(self._connections))

    # ── Sending helpers ─────────────────────────────────────────────────────

    async def _send(self, websocket: WebSocket, payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as exc:
            logger.warning("Failed to send to client: %s", exc)

    async def broadcast(self, payload: dict) -> None:
        """Send a message to ALL connected clients."""
        dead: List[str] = []
        for cid, ws in self._connections.items():
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    async def send_to(self, client_id: str, payload: dict) -> bool:
        """Send a message to ONE specific client. Returns False if not found."""
        ws = self._connections.get(client_id)
        if ws is None:
            return False
        await self._send(ws, payload)
        return True

    # ── Convenience broadcast wrappers ──────────────────────────────────────

    async def notify_new_appointment(self, appointment_data: dict) -> None:
        await self.broadcast({
            "type": "new_appointment",
            "message": f"New appointment booked for {appointment_data.get('client_name', 'client')}",
            "data": appointment_data,
        })

    async def notify_ai_summary(self, appointment_id: int, summary: str, triage: str) -> None:
        await self.broadcast({
            "type": "ai_summary",
            "message": f"AI summary ready — triage: {triage.upper()}",
            "data": {"appointment_id": appointment_id, "summary": summary, "triage": triage},
        })

    async def notify_status_change(self, appointment_id: int, old_status: str, new_status: str) -> None:
        await self.broadcast({
            "type": "status_change",
            "message": f"Appointment #{appointment_id} changed from {old_status} → {new_status}",
            "data": {"appointment_id": appointment_id, "old": old_status, "new": new_status},
        })

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Singleton shared across the whole application
hub = NotificationHub()
