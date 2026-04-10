from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from app.core.config import settings
from app.graph.state import SupervisorState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = SystemMessage(content="""\
You are a Data Governance Assistant. You help users with three types of requests:

1. **Request access to a data product** — the user wants to find and gain access to a dataset.
   Call the `start_access_request` tool with a search query describing what data they need.

2. **Ask a question** — the user has a general question about data governance, the access process, policies, etc.
   Call the `answer_question` tool with their question.

3. **Check status of an existing request** — the user wants to know the status of a previously submitted access request.
   Call the `check_request_status` tool with the request ID if provided.

If the user's intent is unclear, respond with a clarifying question — do NOT call any tool.
Be friendly, concise, and professional.\
""")


@tool
def start_access_request(search_query: str) -> str:
    """Start a data product access request. Call when the user wants to request access to a data product."""
    return ""


@tool
def answer_question(question: str) -> str:
    """Answer a question about data governance or the request access process."""
    return ""


@tool
def check_request_status(request_id: str = "") -> str:
    """Check the status of an existing access request."""
    return ""


SUPERVISOR_TOOLS = [start_access_request, answer_question, check_request_status]

_llm = ChatOpenAI(
    model=settings.MODEL_NAME,
    api_key=settings.OPENAI_API_KEY,
).bind_tools(SUPERVISOR_TOOLS)


def supervisor_node(
    state: SupervisorState,
) -> Command[Literal["request_access", "faq", "status_check", "__end__"]] | dict:
    messages = [SYSTEM_PROMPT] + state["messages"]
    response = _llm.invoke(messages)

    if not response.tool_calls:
        logger.info("Supervisor: no tool call — responding directly")
        return {"messages": [response]}

    tc = response.tool_calls[0]
    logger.info("Supervisor: tool=%s args=%s", tc["name"], tc["args"])

    ack = ToolMessage(
        content=f"Routing to {tc['name']}",
        tool_call_id=tc["id"],
    )

    if tc["name"] == "start_access_request":
        return Command(
            update={
                "messages": [response, ack],
                "active_intent": "request_access",
            },
            goto="request_access",
        )
    elif tc["name"] == "answer_question":
        return Command(
            update={
                "messages": [response, ack],
                "active_intent": "faq",
            },
            goto="faq",
        )
    elif tc["name"] == "check_request_status":
        return Command(
            update={
                "messages": [response, ack],
                "active_intent": "status_check",
            },
            goto="status_check",
        )

    return {"messages": [response]}
