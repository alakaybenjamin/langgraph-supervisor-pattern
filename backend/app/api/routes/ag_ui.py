"""AG-UI streaming endpoint.

POST /ag-ui accepts a ``RunAgentInput`` body and returns an SSE stream of
AG-UI protocol events.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ag_ui.core import RunAgentInput

from app.api.deps import get_ag_ui_service
from app.service.ag_ui_service import AgUiService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ag-ui", tags=["ag-ui"])


@router.post("")
async def ag_ui_stream(
    body: RunAgentInput,
    request: Request,
    svc: AgUiService = Depends(get_ag_ui_service),
) -> StreamingResponse:
    accept = request.headers.get("accept")
    content_type = svc.get_content_type(accept)
    return StreamingResponse(
        svc.stream_run(body, accept_header=accept),
        media_type=content_type,
    )
