"""PlannerState — 노드 사이에 전달하는 상태 (docs/04 3절)."""
from __future__ import annotations

from typing import Any, TypedDict

SEARCH, DETAIL, NEARBY = "search_performances", "get_performance_detail", "search_nearby_places"
PLAN_INTENTS = ("plan_performance", "modify_condition")


class PlannerState(TypedDict, total=False):
    session_id: str
    user_message: str
    # analyze
    intent: str
    intent_reason: str
    conditions: dict[str, Any]
    condition_sources: dict[str, str]
    missing: list[str]
    keyword: str | None
    target_index: int | None
    notices: list[dict[str, str]]
    # plan
    tasks: list[dict[str, Any]]
    query: dict[str, Any]
    plan_version: int
    strategy_index: int
    replanning: bool
    replan_count: int
    relaxed: list[dict[str, Any]]
    replan_reasons: list[str]
    # execute
    phase: str                         # collect | enrich | done
    tool_cache: dict[str, dict]
    seen_ids: list[str]
    round_ids: list[str]
    details: dict[str, dict]
    tool_failures: list[dict[str, Any]]
    places: dict[str, list[dict]]
    # judge
    evaluations: list[dict[str, Any]]
    eligible: list[dict[str, Any]]
    suggestions: list[str]
    next: str
    stop_reason: str | None
    # respond
    response: dict[str, Any]
