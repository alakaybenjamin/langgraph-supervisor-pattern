from __future__ import annotations

from typing import Any

_graph: Any = None
_chat_service: Any = None


def set_graph(graph: Any) -> None:
    global _graph, _chat_service
    _graph = graph

    from app.service.chat_service import ChatService
    _chat_service = ChatService(graph)


def get_chat_service() -> Any:
    if _chat_service is None:
        raise RuntimeError("Chat service not initialized — graph not built yet")
    return _chat_service
