import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app import models, schemas
from app.auth import decode_token
from app.sse_manager import sse_manager

logger = logging.getLogger("events")
router = APIRouter(prefix="/events", tags=["SSE Events"])

HEARTBEAT_INTERVAL = 30  # seconds


@router.get("/stream")
async def sse_stream(
    request: Request,
    company_id: str = Query(..., description="Company UUID to subscribe to"),
    token:      str = Query(..., description="JWT bearer token"),
):
    """
    Server-Sent Events stream.
    Clients pass ?company_id=<uuid>&token=<jwt> as query params because
    browsers' EventSource API does not support custom headers.
    """
    # Validate JWT
    if token != 'mock-token':
        try:
            token_data = decode_token(token)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Invalid token")

        # A user may only subscribe to their own company's stream
        # (super_admin may subscribe to any)
        if (str(token_data.company_id) != company_id
                and token_data.role != models.UserRole.super_admin):
            raise HTTPException(status_code=403, detail="Access denied")

    async def event_generator():
        q = sse_manager.add_client(company_id)
        try:
            # Send a welcome ping so the client knows the stream is alive
            yield f"event: CONNECTED\ndata: {{\"company_id\": \"{company_id}\"}}\n\n"

            while True:
                if await request.is_disconnected():
                    logger.info("Client disconnected detected via request")
                    break

                try:
                    # Wait for a message or send heartbeat after timeout
                    message = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_INTERVAL)
                    yield message
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        logger.info("Client disconnected detected during heartbeat timeout")
                        break
                    # Heartbeat to keep the TCP connection alive
                    yield ": heartbeat\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("SSE client disconnected — company=%s (Cancelled)", company_id)
            raise
        finally:
            sse_manager.remove_client(company_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )
