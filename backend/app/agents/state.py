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
    places_failed: list[str]           # 주변 장소 조회가 '실패'한 공연장 (결과 없음과 구분)
    # judge
    evaluations: list[dict[str, Any]]
    eligible: list[dict[str, Any]]
    suggestions: list[str]
    next: str
    stop_reason: str | None
    # F3021 Planner·Worker
    replan_requests: list[dict[str, Any]]   # Worker → Planner 계획 변경 요청 (이번 라운드)
    verification: dict[str, Any]            # 로깅 Agent 검증 결과
    rebuild_requested: bool
    rebuilt: bool
    worker_retry_disabled: bool
    route_after_plan: str                   # execute | judge
    # respond
    response: dict[str, Any]
