from __future__ import annotations

import json
import logging
import traceback

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_chat_service
from app.schema.chat import ChatRequest, ChatResponse
from app.service.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    svc: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    try:
        result = await svc.invoke(
            action=body.action,
            message=body.message,
            resume_data=body.resume_data,
            thread_id=body.thread_id,
            user_id=body.user_id,
        )
        return ChatResponse(**result)
    except Exception as exc:
        logger.error("Chat error: %s\n%s", exc, traceback.format_exc())
        return ChatResponse(
            type="error",
            content=f"An error occurred: {exc}",
            thread_id=body.thread_id,
        )


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    svc: ChatService = Depends(get_chat_service),
) -> EventSourceResponse:
    async def event_generator():
        try:
            async for event in svc.stream(
                action=body.action,
                message=body.message,
                resume_data=body.resume_data,
                thread_id=body.thread_id,
                user_id=body.user_id,
            ):
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
        except Exception as exc:
            logger.error("Stream error: %s\n%s", exc, traceback.format_exc())
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "content": str(exc)}),
            }

    return EventSourceResponse(event_generator())
