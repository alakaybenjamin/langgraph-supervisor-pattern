from __future__ import annotations

from typing import Any

_graph: Any = None
_chat_service: Any = None
_ag_ui_service: Any = None


def set_graph(graph: Any) -> None:
    global _graph, _chat_service, _ag_ui_service
    _graph = graph

    from app.service.chat_service import ChatService
    _chat_service = ChatService(graph)

    from app.service.ag_ui_service import AgUiService
    _ag_ui_service = AgUiService(graph)


def get_chat_service() -> Any:
    if _chat_service is None:
        raise RuntimeError("Chat service not initialized — graph not built yet")
    return _chat_service


def get_ag_ui_service() -> Any:
    if _ag_ui_service is None:
        raise RuntimeError("AG-UI service not initialized — graph not built yet")
    return _ag_ui_service
