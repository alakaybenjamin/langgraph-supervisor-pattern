from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from app.core.llm import get_chat_llm
from app.graph.state import SupervisorState

logger = logging.getLogger(__name__)


def _get_faq_service():
    from app.service.faq_service import FaqService
    return FaqService()


def faq_node(state: SupervisorState) -> dict:
    last_msg = state["messages"][-1]
    question = (
        last_msg.tool_calls[0]["args"].get("question", "")
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls
        else last_msg.content
    )

    logger.info("FAQ node: searching for '%s'", question)
    faq_service = _get_faq_service()
    search_results = faq_service.search(question)

    context = "\n\n".join(
        f"Source: {r.get('url', 'N/A')}\n{r.get('content', '')}"
        for r in search_results
    )

    llm = get_chat_llm()
    synthesis_prompt = [
        {"role": "system", "content": "You are a helpful data governance assistant. Use the search results below to answer the user's question concisely. If the results don't contain relevant information, say so honestly."},
        {"role": "user", "content": f"Question: {question}\n\nSearch Results:\n{context}"},
    ]

    answer = llm.invoke(synthesis_prompt)
    return {"messages": [AIMessage(content=answer.content)]}
