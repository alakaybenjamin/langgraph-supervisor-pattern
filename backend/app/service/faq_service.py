from __future__ import annotations

import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)


class FaqService:
    def __init__(self) -> None:
        os.environ.setdefault("TAVILY_API_KEY", settings.TAVILY_API_KEY)

        from langchain_community.tools.tavily_search import TavilySearchResults
        self._search = TavilySearchResults(max_results=3)

    def search(self, query: str) -> list[dict]:
        logger.info("Tavily search: %s", query)
        return self._search.invoke(query)
