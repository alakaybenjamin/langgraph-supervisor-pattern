from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph.state import AccessRequestState
from app.graph.subgraphs.request_access.nodes.confirm import confirm_node
from app.graph.subgraphs.request_access.nodes.fill_form import fill_form_node
from app.graph.subgraphs.request_access.nodes.narrow import narrow_node
from app.graph.subgraphs.request_access.nodes.review_cart import review_cart_node
from app.graph.subgraphs.request_access.nodes.search_app import search_app_node
from app.graph.subgraphs.request_access.nodes.show_results import show_results_node
from app.graph.subgraphs.request_access.nodes.submit import submit_node


def _route_after_narrow(state: AccessRequestState) -> str:
    if state.get("selected_domain") and state.get("selected_type"):
        return "show_results"
    return "narrow"


def _route_after_show_results(state: AccessRequestState) -> str:
    step = state.get("current_step", "")
    if step == "search_app":
        return "search_app"
    if step == "narrow":
        return "narrow"
    if step == "fill_form":
        return "fill_form"
    return "review_cart"


def _route_after_review_cart(state: AccessRequestState) -> str:
    step = state.get("current_step", "")
    if step == "narrow":
        return "narrow"
    return "fill_form"


def _route_after_fill_form(state: AccessRequestState) -> str:
    step = state.get("current_step", "")
    if step == "fill_form":
        return "fill_form"
    if step == "narrow":
        return "narrow"
    if step == "review_cart":
        return "review_cart"
    return "confirm"


def _route_after_search_app(state: AccessRequestState) -> str:
    if state.get("current_step") == "search_app":
        return "search_app"
    return "review_cart"


def _route_after_confirm(state: AccessRequestState) -> str:
    step = state.get("current_step", "")
    if step == "submit":
        return "submit"
    if step == "narrow":
        return "narrow"
    if step == "fill_form":
        return "fill_form"
    return "fill_form"


def build_request_access_subgraph() -> StateGraph:
    builder = StateGraph(AccessRequestState)

    builder.add_node("narrow", narrow_node)
    builder.add_node("show_results", show_results_node)
    builder.add_node("search_app", search_app_node)
    builder.add_node("review_cart", review_cart_node)
    builder.add_node("fill_form", fill_form_node)
    builder.add_node("confirm", confirm_node)
    builder.add_node("submit", submit_node)

    builder.add_edge(START, "narrow")
    builder.add_conditional_edges("narrow", _route_after_narrow, ["narrow", "show_results"])
    builder.add_conditional_edges("show_results", _route_after_show_results, ["search_app", "narrow", "fill_form", "review_cart"])
    builder.add_conditional_edges("search_app", _route_after_search_app, ["search_app", "review_cart"])
    builder.add_conditional_edges("review_cart", _route_after_review_cart, ["narrow", "fill_form"])
    builder.add_conditional_edges("fill_form", _route_after_fill_form, ["fill_form", "confirm", "narrow", "review_cart"])
    builder.add_conditional_edges("confirm", _route_after_confirm, ["submit", "narrow", "fill_form"])
    builder.add_edge("submit", END)

    return builder
