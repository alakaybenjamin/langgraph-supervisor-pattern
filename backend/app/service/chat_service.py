from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ChatService:
    """Thin adapter between the HTTP layer and the compiled parent graph.

    Resume semantics:
      * ``action=resume`` + structured ``resume_data``: forwarded as
        ``Command(resume=resume_data)`` to the paused native interrupt.
      * ``action=send`` with a pending interrupt on the thread: forwarded as
        ``Command(resume={"action": "user_message", "text": message})`` so the
        workflow router can classify free-text (FAQ / nav / plain).
      * ``action=send`` without a pending interrupt: appended as a new
        ``HumanMessage`` to restart from START (supervisor_router).
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def _has_pending_interrupt(self, config: dict) -> bool:
        state = await self._graph.aget_state(config)
        if state and state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    return True
        return False

    async def _build_input(
        self, *, action: str, message: str, resume_data: dict,
        thread_id: str, user_id: str,
    ) -> tuple[Any, str]:
        if not thread_id:
            thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        if action == "resume":
            return Command(resume=resume_data), thread_id

        if await self._has_pending_interrupt(config):
            logger.info("chat: pending interrupt — wrapping text as resume payload")
            return (
                Command(
                    resume={"action": "user_message", "text": message},
                ),
                thread_id,
            )

        return (
            {
                "messages": [HumanMessage(content=message)],
                "thread_id": thread_id,
                "user_id": user_id,
            },
            thread_id,
        )

    # -- JSON (non-streaming) ------------------------------------------------

    async def invoke(
        self, *, action: str, message: str, resume_data: dict,
        thread_id: str, user_id: str,
    ) -> dict:
        input_data, thread_id = await self._build_input(
            action=action, message=message, resume_data=resume_data,
            thread_id=thread_id, user_id=user_id,
        )
        config = {"configurable": {"thread_id": thread_id}}
        logger.info("Invoking graph  action=%s  thread=%s", action, thread_id)
        result = await self._graph.ainvoke(input_data, config)
        return await self._format_result(result, thread_id, config)

    async def _format_result(self, result: dict, thread_id: str, config: dict) -> dict:
        state = await self._graph.aget_state(config)
        if state and state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    val = task.interrupts[0].value
                    return {
                        "type": "interrupt",
                        "content": "",
                        "thread_id": thread_id,
                        "interrupt": {
                            "type": "interrupt",
                            "interrupt_value": val,
                            "thread_id": thread_id,
                        },
                    }

        messages = (result or {}).get("messages", [])
        last_ai = ""
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "ai" and getattr(msg, "content", None):
                last_ai = msg.content
                break

        return {
            "type": "message",
            "content": last_ai,
            "thread_id": thread_id,
            "interrupt": None,
        }

    # -- SSE (streaming) -----------------------------------------------------

    async def stream(
        self, *, action: str, message: str, resume_data: dict,
        thread_id: str, user_id: str,
    ) -> AsyncIterator[dict]:
        input_data, thread_id = await self._build_input(
            action=action, message=message, resume_data=resume_data,
            thread_id=thread_id, user_id=user_id,
        )
        config = {"configurable": {"thread_id": thread_id}}
        logger.info("Streaming graph  action=%s  thread=%s", action, thread_id)

        full_content = ""

        async for mode, chunk in self._graph.astream(
            input_data, config, stream_mode=["messages", "custom"]
        ):
            if mode == "messages":
                token_chunk, _meta = chunk
                if (
                    getattr(token_chunk, "type", None) == "AIMessageChunk"
                    and token_chunk.content
                    and not getattr(token_chunk, "tool_call_chunks", None)
                ):
                    full_content += token_chunk.content
                    yield {"event": "token", "data": {"token": token_chunk.content}}
            elif mode == "custom" and isinstance(chunk, dict) and "type" in chunk:
                yield {
                    "event": "interrupt",
                    "data": {
                        "type": "interrupt",
                        "interrupt_value": chunk,
                        "thread_id": thread_id,
                    },
                }

        state = await self._graph.aget_state(config)
        if state and state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    val = task.interrupts[0].value
                    logger.info(
                        "Interrupt detected  thread=%s  type=%s",
                        thread_id, val.get("type", "unknown"),
                    )
                    yield {
                        "event": "interrupt",
                        "data": {
                            "type": "interrupt",
                            "interrupt_value": val,
                            "thread_id": thread_id,
                        },
                    }
                    return

        state_values = getattr(state, "values", {}) or {}
        state_messages = state_values.get("messages", [])
        final_content = full_content
        for msg in reversed(state_messages):
            if getattr(msg, "type", None) == "ai" and getattr(msg, "content", None):
                final_content = msg.content or full_content
                break

        yield {
            "event": "done",
            "data": {
                "type": "message",
                "content": final_content,
                "thread_id": thread_id,
            },
        }
