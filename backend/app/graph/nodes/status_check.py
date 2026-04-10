from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from app.graph.state import SupervisorState
from app.service.status_service import StatusService

logger = logging.getLogger(__name__)

_status_service = StatusService()


def status_check_node(state: SupervisorState) -> dict:
    last_msg = state["messages"][-1]
    request_id = ""
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        request_id = last_msg.tool_calls[0]["args"].get("request_id", "")

    if request_id:
        result = _status_service.get_status(request_id)
        if result:
            lines = [
                f"**Request {result['id']}**",
                f"- Product: {result['product']}",
                f"- Status: {result['status']}",
                f"- Submitted: {result['submitted']}",
                f"- Last Updated: {result['updated']}",
            ]
            if "reason" in result:
                lines.append(f"- Reason: {result['reason']}")
            content = "\n".join(lines)
        else:
            content = f"I couldn't find a request with ID **{request_id}**. Please check the ID and try again."
    else:
        all_requests = _status_service.list_all()
        if all_requests:
            lines = ["Here are all tracked requests:\n"]
            for r in all_requests:
                lines.append(f"- **{r['id']}**: {r['product']} — *{r['status']}*")
            content = "\n".join(lines)
        else:
            content = "There are no tracked requests at the moment."

    return {"messages": [AIMessage(content=content)]}
