from __future__ import annotations

import logging
import traceback

from fastapi import APIRouter, Depends

from app.api.deps import get_chat_service
from app.schema.chat import ChatRequest, ChatResumeRequest, ChatResponse
from app.service.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    svc: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    try:
        result = await svc.send_message(
            message=body.message,
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


@router.post("/resume", response_model=ChatResponse)
async def chat_resume(
    body: ChatResumeRequest,
    svc: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    try:
        result = await svc.resume(
            resume_data=body.resume_data,
            thread_id=body.thread_id,
            user_id=body.user_id,
        )
        return ChatResponse(**result)
    except Exception as exc:
        logger.error("Resume error: %s\n%s", exc, traceback.format_exc())
        return ChatResponse(
            type="error",
            content=f"An error occurred: {exc}",
            thread_id=body.thread_id,
        )
