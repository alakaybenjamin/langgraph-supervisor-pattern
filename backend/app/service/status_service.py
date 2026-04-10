from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MOCK_STATUSES: dict[str, dict] = {
    "REQ-001": {
        "id": "REQ-001",
        "product": "Customer Demographics",
        "status": "approved",
        "submitted": "2025-12-01",
        "updated": "2025-12-05",
    },
    "REQ-002": {
        "id": "REQ-002",
        "product": "Clinical Trial Results",
        "status": "pending",
        "submitted": "2026-03-15",
        "updated": "2026-03-15",
    },
    "REQ-003": {
        "id": "REQ-003",
        "product": "Sales Territory Performance",
        "status": "rejected",
        "submitted": "2026-01-20",
        "updated": "2026-02-01",
        "reason": "Insufficient business justification",
    },
}


class StatusService:
    def get_status(self, request_id: str) -> dict | None:
        logger.info("Status lookup: %s", request_id)
        return MOCK_STATUSES.get(request_id.upper())

    def list_all(self) -> list[dict]:
        return list(MOCK_STATUSES.values())
