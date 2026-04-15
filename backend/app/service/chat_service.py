from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def _build_input(
        self, *, action: str, message: str, resume_data: dict,
        thread_id: str, user_id: str,
    ) -> tuple[Any, str]:
        """Return ``(graph_input, thread_id)`` for both JSON and SSE paths."""
        if not thread_id:
            thread_id = str(uuid.uuid4())

        if action == "resume":
            return Command(resume=resume_data), thread_id

        return {
            "messages": [HumanMessage(content=message)],
            "thread_id": thread_id,
            "user_id": user_id,
        }, thread_id

    # -- JSON (non-streaming) ------------------------------------------------

    async def invoke(
        self, *, action: str, message: str, resume_data: dict,
        thread_id: str, user_id: str,
    ) -> dict:
        input_data, thread_id = self._build_input(
            action=action, message=message, resume_data=resume_data,
            thread_id=thread_id, user_id=user_id,
        )
        config = {"configurable": {"thread_id": thread_id}}

        logger.info("Invoking graph  action=%s  thread=%s", action, thread_id)
        result = await self._graph.ainvoke(input_data, config)

        return self._format_result(result, thread_id)

    def _format_result(self, result: dict, thread_id: str) -> dict:
        if "__interrupt__" in result and result["__interrupt__"]:
            interrupts = result["__interrupt__"]
            interrupt_val = interrupts[0].value if interrupts else {}
            return {
                "type": "interrupt",
                "content": "",
                "thread_id": thread_id,
                "interrupt": {
                    "type": "interrupt",
                    "interrupt_value": interrupt_val,
                    "thread_id": thread_id,
                },
            }

        messages = result.get("messages", [])
        last_ai = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.type == "ai":
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
        """Yields ``{"event": <name>, "data": <payload>}`` dicts for SSE."""
        input_data, thread_id = self._build_input(
            action=action, message=message, resume_data=resume_data,
            thread_id=thread_id, user_id=user_id,
        )
        config = {"configurable": {"thread_id": thread_id}}

        logger.info("Streaming graph  action=%s  thread=%s", action, thread_id)

        full_content = ""

        async for mode, chunk in self._graph.astream(
            input_data, config, stream_mode=["messages", "values"]
        ):
            if mode == "messages":
                token_chunk, _metadata = chunk
                if hasattr(token_chunk, "content") and token_chunk.content:
                    full_content += token_chunk.content
                    yield {
                        "event": "token",
                        "data": {"token": token_chunk.content},
                    }

        # After the stream ends, check the checkpoint for pending interrupts.
        # astream() does NOT emit __interrupt__ in values chunks — the
        # interrupt info is only stored in the checkpoint state.
        state = await self._graph.aget_state(config)
        if state.tasks:
            for task in state.tasks:
                if task.interrupts:
                    interrupt_val = task.interrupts[0].value
                    logger.info("Interrupt detected  thread=%s  type=%s",
                                thread_id, interrupt_val.get("type", "unknown"))
                    yield {
                        "event": "interrupt",
                        "data": {
                            "type": "interrupt",
                            "interrupt_value": interrupt_val,
                            "thread_id": thread_id,
                        },
                    }
                    return

        yield {
            "event": "done",
            "data": {
                "type": "message",
                "content": full_content,
                "thread_id": thread_id,
            },
        }
