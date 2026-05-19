"""
SSE Manager — global registry of connected dashboard clients.
Thread-safe enough for a single-process FastAPI / uvicorn deployment.
"""
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List
from uuid import UUID

logger = logging.getLogger("sse_manager")


class SSEManager:
    """
    Manages Server-Sent Events connections per company.
    Each client is represented as an asyncio.Queue that the stream
    generator drains and yields to the HTTP response.
    """

    def __init__(self):
        # company_id (str) → list of asyncio.Queue
        self._clients: Dict[str, List[asyncio.Queue]] = defaultdict(list)

    # ── client lifecycle ──────────────────────────────────────────────────────

    def add_client(self, company_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients[company_id].append(q)
        logger.info("SSE client connected  — company=%s  total=%d",
                    company_id, len(self._clients[company_id]))
        return q

    def remove_client(self, company_id: str, q: asyncio.Queue) -> None:
        try:
            self._clients[company_id].remove(q)
        except ValueError:
            pass
        logger.info("SSE client disconnected — company=%s  total=%d",
                    company_id, len(self._clients[company_id]))

    # ── broadcasting ──────────────────────────────────────────────────────────

    async def broadcast(self, company_id: str, event_type: str, data: Any) -> None:
        """Send an SSE event to every connected client for a given company."""
        queues = self._clients.get(str(company_id), [])
        if not queues:
            return

        payload = json.dumps({"type": event_type, "data": data}, default=str)
        message = f"data: {payload}\n\n"

        dead: List[asyncio.Queue] = []
        for q in queues:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for company=%s — dropping client", company_id)
                dead.append(q)

        for q in dead:
            self.remove_client(str(company_id), q)

    def active_clients(self, company_id: str) -> int:
        return len(self._clients.get(str(company_id), []))

    def total_clients(self) -> int:
        return sum(len(v) for v in self._clients.values())


# Singleton used across the application
sse_manager = SSEManager()
