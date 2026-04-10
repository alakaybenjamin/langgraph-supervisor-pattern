from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def send_message(
        self,
        message: str,
        thread_id: str = "",
        user_id: str = "anonymous",
    ) -> dict:
        if not thread_id:
            thread_id = str(uuid.uuid4())

        config = {"configurable": {"thread_id": thread_id}}
        input_state = {
            "messages": [HumanMessage(content=message)],
            "thread_id": thread_id,
            "user_id": user_id,
        }

        logger.info("Invoking graph  thread=%s", thread_id)
        result = await self._graph.ainvoke(input_state, config)

        return self._format_result(result, thread_id)

    async def resume(
        self,
        resume_data: dict,
        thread_id: str,
        user_id: str = "anonymous",
    ) -> dict:
        config = {"configurable": {"thread_id": thread_id}}

        logger.info("Resuming graph  thread=%s", thread_id)
        result = await self._graph.ainvoke(
            Command(resume=resume_data), config
        )

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
