from __future__ import annotations

import logging

from langchain_chroma import Chroma

from app.core.llm import get_embeddings

logger = logging.getLogger(__name__)

DATA_PRODUCTS = [
    {
        "text": "Customer Demographics - PII dataset containing customer age, gender, location, income bracket, and loyalty tier. Updated weekly from CRM system.",
        "metadata": {"domain": "commercial", "owner": "CDO", "sensitivity": "high", "id": "dp-001", "product_type": "default"},
    },
    {
        "text": "Clinical Trial Results - Phase III trial outcomes for oncology pipeline. Contains patient-level efficacy and safety data.",
        "metadata": {"domain": "r_and_d", "owner": "Clinical Data Management", "sensitivity": "critical", "id": "dp-002", "product_type": "ddf"},
    },
    {
        "text": "Pharmacovigilance Reports - Adverse event reports aggregated from global safety databases. CIOMS-compliant.",
        "metadata": {"domain": "safety", "owner": "Drug Safety", "sensitivity": "critical", "id": "dp-003", "product_type": "ddf"},
    },
    {
        "text": "Sales Territory Performance - Monthly sales revenue by territory, product line, and rep. Sourced from SAP.",
        "metadata": {"domain": "commercial", "owner": "Commercial Analytics", "sensitivity": "medium", "id": "dp-004", "product_type": "default"},
    },
    {
        "text": "Supply Chain Inventory - Real-time inventory levels across distribution centres. Refreshed hourly.",
        "metadata": {"domain": "operations", "owner": "Supply Chain", "sensitivity": "medium", "id": "dp-005", "product_type": "default"},
    },
    {
        "text": "Employee HR Records - Headcount, department assignments, compensation bands, and attrition flags.",
        "metadata": {"domain": "hr", "owner": "People Analytics", "sensitivity": "high", "id": "dp-006", "product_type": "default"},
    },
    {
        "text": "Marketing Campaign Attribution - Multi-touch attribution data linking campaigns to conversions and revenue.",
        "metadata": {"domain": "commercial", "owner": "Marketing Analytics", "sensitivity": "medium", "id": "dp-007", "product_type": "default"},
    },
    {
        "text": "Genomics Sequencing Data - Whole genome sequencing results from biobank participants. Research-only.",
        "metadata": {"domain": "r_and_d", "owner": "Genomics Lab", "sensitivity": "critical", "id": "dp-008", "product_type": "ddf"},
    },
    {
        "text": "Financial General Ledger - Chart of accounts with monthly journal entries and cost centre allocations.",
        "metadata": {"domain": "finance", "owner": "Finance Ops", "sensitivity": "high", "id": "dp-009", "product_type": "default"},
    },
    {
        "text": "Real World Evidence - Claims and EHR data aggregated from external partners for outcomes research.",
        "metadata": {"domain": "r_and_d", "owner": "RWE Team", "sensitivity": "critical", "id": "dp-010", "product_type": "ddf"},
    },
    {
        "text": "IT Asset Inventory - Hardware and software asset records including license compliance status.",
        "metadata": {"domain": "it", "owner": "IT Asset Management", "sensitivity": "low", "id": "dp-011", "product_type": "default"},
    },
    {
        "text": "Patient Registry - De-identified patient registry for rare disease research across 12 countries.",
        "metadata": {"domain": "r_and_d", "owner": "Medical Affairs", "sensitivity": "critical", "id": "dp-012", "product_type": "ddf"},
    },
    {
        "text": "Digital Engagement Analytics - Website and app behavioural telemetry: page views, clicks, session duration.",
        "metadata": {"domain": "commercial", "owner": "Digital Team", "sensitivity": "low", "id": "dp-013", "product_type": "default"},
    },
    {
        "text": "Regulatory Submissions Archive - eCTD submissions and FDA/EMA correspondence. Document-level metadata.",
        "metadata": {"domain": "regulatory", "owner": "Regulatory Affairs", "sensitivity": "high", "id": "dp-014", "product_type": "onyx"},
    },
    {
        "text": "Manufacturing Batch Records - Electronic batch records with in-process controls and release testing results.",
        "metadata": {"domain": "operations", "owner": "Manufacturing QA", "sensitivity": "high", "id": "dp-015", "product_type": "onyx"},
    },
]


class SearchService:
    def __init__(self) -> None:
        embeddings = get_embeddings()
        self._store = Chroma(
            embedding_function=embeddings,
            collection_name="data_products",
        )
        self._seed()

    def _seed(self) -> None:
        texts = [dp["text"] for dp in DATA_PRODUCTS]
        metadatas = [dp["metadata"] for dp in DATA_PRODUCTS]
        ids = [dp["metadata"]["id"] for dp in DATA_PRODUCTS]
        self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        logger.info("Seeded vector store with %d data products", len(texts))

    def search(self, query: str, k: int = 5) -> list[dict]:
        results = self._store.similarity_search_with_score(query, k=k)
        return [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score),
            }
            for doc, score in results
        ]

    def search_with_filters(
        self,
        query: str = "",
        domain: str = "all",
        product_type: str = "all",
        k: int = 10,
    ) -> list[dict]:
        """Search with optional metadata filters applied."""
        where_clauses: list[dict] = []
        if domain and domain != "all":
            where_clauses.append({"domain": domain})
        if product_type and product_type != "all":
            where_clauses.append({"product_type": product_type})

        where = None
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}

        effective_query = query or "data product"
        results = self._store.similarity_search_with_score(
            effective_query, k=k, filter=where
        )
        return [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score),
            }
            for doc, score in results
        ]

    @staticmethod
    def get_facets() -> dict:
        """Return available facet values from the corpus."""
        domains = sorted({dp["metadata"]["domain"] for dp in DATA_PRODUCTS})
        product_types = sorted({dp["metadata"]["product_type"] for dp in DATA_PRODUCTS})
        sensitivities = sorted({dp["metadata"]["sensitivity"] for dp in DATA_PRODUCTS})
        return {
            "domains": domains,
            "product_types": product_types,
            "sensitivities": sensitivities,
        }

    @staticmethod
    def get_all_products() -> list[dict]:
        """Return all data products without vector search."""
        return [
            {
                "content": dp["text"],
                "metadata": dp["metadata"],
                "score": 1.0,
            }
            for dp in DATA_PRODUCTS
        ]
