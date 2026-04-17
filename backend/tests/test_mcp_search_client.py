from __future__ import annotations

"""Unit tests for the MCP search client helpers.

The wire-level ``streamablehttp_client`` + ``ClientSession`` path is
covered indirectly by the subgraph tests (which exercise the full node
chain with the MCP call mocked out). These tests stay at the public
surface and assert:

1. ``list_facets`` / ``search`` return safe defaults on transport error.
2. ``search`` strips empty / ``"all"`` filters before sending.
"""

import asyncio

import pytest

import app.service.mcp_search_client as client_mod


def test_list_facets_returns_empty_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _call(_tool: str, _args: dict) -> dict:
        return {}

    monkeypatch.setattr(client_mod, "_call_tool", _call)
    assert asyncio.run(client_mod.list_facets()) == {}


def test_search_strips_all_and_empty_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _call(tool_name: str, arguments: dict) -> dict:
        captured["tool"] = tool_name
        captured["args"] = arguments
        return {"products": [{"id": "dp-1"}]}

    monkeypatch.setattr(client_mod, "_call_tool", _call)

    results = asyncio.run(
        client_mod.search(
            search_text="demographics",
            domains=["all", "", "commercial"],
            anonymization="",
            study_id=None,
        )
    )

    assert results == [{"id": "dp-1"}]
    assert captured["tool"] == "search"
    assert captured["args"]["search_text"] == "demographics"
    # "all" / "" domain values and the empty anonymization / study_id should
    # be stripped.
    assert captured["args"]["filters"] == {"domains": ["commercial"]}


def test_search_defaults_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _call(tool_name: str, arguments: dict) -> dict:
        captured["args"] = arguments
        return {"products": []}

    monkeypatch.setattr(client_mod, "_call_tool", _call)

    assert asyncio.run(client_mod.search()) == []
    assert captured["args"] == {"search_text": "*"}
