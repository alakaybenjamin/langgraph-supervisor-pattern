from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from app.graph.prompts import (
    STATUS_DETAIL_HEADER_TEMPLATE,
    STATUS_DETAIL_PRODUCT_TEMPLATE,
    STATUS_DETAIL_REASON_TEMPLATE,
    STATUS_DETAIL_STATUS_TEMPLATE,
    STATUS_DETAIL_SUBMITTED_TEMPLATE,
    STATUS_DETAIL_UPDATED_TEMPLATE,
    STATUS_EMPTY_MESSAGE,
    STATUS_LIST_HEADER,
    STATUS_LIST_ITEM_TEMPLATE,
    STATUS_NOT_FOUND_TEMPLATE,
)
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
                STATUS_DETAIL_HEADER_TEMPLATE.format(id=result["id"]),
                STATUS_DETAIL_PRODUCT_TEMPLATE.format(product=result["product"]),
                STATUS_DETAIL_STATUS_TEMPLATE.format(status=result["status"]),
                STATUS_DETAIL_SUBMITTED_TEMPLATE.format(submitted=result["submitted"]),
                STATUS_DETAIL_UPDATED_TEMPLATE.format(updated=result["updated"]),
            ]
            if "reason" in result:
                lines.append(
                    STATUS_DETAIL_REASON_TEMPLATE.format(reason=result["reason"])
                )
            content = "\n".join(lines)
        else:
            content = STATUS_NOT_FOUND_TEMPLATE.format(request_id=request_id)
    else:
        all_requests = _status_service.list_all()
        if all_requests:
            lines = [STATUS_LIST_HEADER]
            for r in all_requests:
                lines.append(
                    STATUS_LIST_ITEM_TEMPLATE.format(
                        id=r["id"], product=r["product"], status=r["status"]
                    )
                )
            content = "\n".join(lines)
        else:
            content = STATUS_EMPTY_MESSAGE
    return {"messages": [AIMessage(content=content)]}
