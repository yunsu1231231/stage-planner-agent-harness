"""plan 노드 — F3006 작업 계획 수립 (LLM이 Tool 선택 → 규칙 검증), F3009 재계획 (규칙, LLM 없음)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ...tools.codes import resolve_region
from ..prompts import PLAN_SYSTEM
from ..runtime import RunContext
from ..state import DETAIL, NEARBY, PLAN_INTENTS, SEARCH, PlannerState

STRATEGIES = ["expand_pool", "drop_genre", "widen_region"]       # docs/04 4.2 재계획 사다리
EXPANDED_LIMIT = 40


def _applicable(strategy: str, query: dict[str, Any]) -> bool:
    if strategy == "expand_pool":
        return query.get("limit", 20) < EXPANDED_LIMIT
    if strategy == "drop_genre":
        return bool(query.get("genre"))
    if strategy == "widen_region":
        region = resolve_region(query["region"]) if query.get("region") else None
        return bool(region and "signgucodesub" in region)
    return False


def next_strategy(query: dict[str, Any], index: int, skip: set[str] | frozenset = frozenset()) -> tuple[int, str] | None:
    """index: 지금까지 쓴 마지막 전략 번호 (0 = 최초 계획). skip: 이번에 의미 없는 전략."""
    for i in range(index + 1, len(STRATEGIES) + 1):
        if STRATEGIES[i - 1] not in skip and _applicable(STRATEGIES[i - 1], query):
            return i, STRATEGIES[i - 1]
    return None


def skip_for(state: PlannerState) -> set[str]:
    """Worker 가 '후보 검색 결과 없음'으로 계획 변경을 요청했다면 후보 풀 확장은 의미 없다 (F3021 반영)."""
    return {"expand_pool"} if any(r["tool"] == SEARCH and r["code"] == "NO_RESULT"
                                  for r in state.get("replan_requests", [])) else set()


def worker_reason(state: PlannerState) -> str:
    reqs = state.get("replan_requests", [])
    return ("; Worker 요청: " + ", ".join(f"{r['tool']} {r['code']}" for r in reqs)) if reqs else ""


def _send_tasks(run: RunContext, plan_version: int, strategy: str, tasks: list[dict[str, Any]]) -> None:
    if run.deps.mode == "planner_worker":
        run.message("plan", "Planner", "Worker", "task_list", {
            "plan_version": plan_version, "strategy": strategy,
            "tasks": [{k: t[k] for k in ("id", "tool", "args", "fixed_args", "phase")} for t in tasks]})


def _required(state: PlannerState) -> list[str]:
    intent, cond = state["intent"], state["conditions"]
    if intent == "fact_query" and not state.get("keyword"):
        return [DETAIL]                                  # 직전 추천 번호로 상세만 조회
    tools = [SEARCH, DETAIL]
    if intent in PLAN_INTENTS and cond.get("place_category"):
        tools.append(NEARBY)
    return tools


FACT_WINDOW_DAYS = 60   # 공연명 질문은 '오늘 공연 중'에 한정하지 않는다 (비교 실험 C4에서 발견)


def _search_args(state: PlannerState, query: dict[str, Any], run: RunContext) -> dict[str, Any]:
    cond = state["conditions"]
    args = {"date": cond.get("date"), "region": query.get("region"), "genre": query.get("genre"),
            "keyword": query.get("keyword"), "limit": query.get("limit", 20)}
    if state["intent"] == "fact_query":
        start = date.fromisoformat(cond["date"]) if cond.get("date") else run.deps.today()
        args["end_date"] = (start + timedelta(days=FACT_WINDOW_DAYS)).isoformat()
    return {k: v for k, v in args.items() if v is not None}


def _tasks(state: PlannerState, tools: list[str], query: dict[str, Any], run: RunContext) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for i, tool in enumerate(tools, 1):
        if tool == SEARCH:
            args = _search_args(state, query, run)
            # 사용자 조건으로 채운 인자는 고정 (Worker 가 못 바꿈). 검색어는 검색 표현이라 고정하지 않는다.
            tasks.append({"id": f"t{i}", "tool": tool, "args": args, "phase": "collect", "depends_on": [],
                          "fixed_args": [k for k in ("date", "region", "genre") if k in args]})
        elif tool == DETAIL:
            if SEARCH in tools:
                args = {"performance_id": "<search.items[].performance_id>"}
                fixed: list[str] = []
            else:
                rec = run.memory.last_recommendations[state["target_index"] - 1]
                args, fixed = {"performance_id": rec["performance_id"]}, ["performance_id"]
            tasks.append({"id": f"t{i}", "tool": tool, "args": args, "phase": "collect",
                          "depends_on": [t["id"] for t in tasks if t["tool"] == SEARCH], "fixed_args": fixed})
        elif tool == NEARBY:
            tasks.append({"id": f"t{i}", "tool": tool, "phase": "enrich", "fixed_args": ["category"],
                          "args": {"venue_id": "<judge.eligible[].venue_id>",
                                   "category": state["conditions"]["place_category"]},
                          "depends_on": [t["id"] for t in tasks if t["tool"] == DETAIL]})
    return tasks


def plan(state: PlannerState, run: RunContext) -> dict[str, Any]:
    if state.get("rebuild_requested"):
        return _rebuild(state, run)
    if state.get("replanning"):
        return _replan(state, run)

    required = _required(state)
    proposed: list[str] | None = None
    run.llm_calls += 1
    try:
        bound = run.deps.llm.bind_tools(run.deps.registry.as_langchain_tools())
        request = {"intent": state["intent"], "conditions": state["conditions"], "keyword": state.get("keyword")}
        msg = bound.invoke([SystemMessage(PLAN_SYSTEM), HumanMessage(json.dumps(request, ensure_ascii=False))])
        proposed = list(dict.fromkeys(tc["name"] for tc in msg.tool_calls))
        run.emit("llm.decision", "plan", decision=proposed, reason=msg.content or "",
                 proposed_args={tc["name"]: tc.get("args", {}) for tc in msg.tool_calls})
    except Exception as e:  # noqa: BLE001
        run.emit("plan.corrected", "plan", reason="llm_failed", detail=type(e).__name__, added=required, removed=[])

    if proposed is not None:
        added = [t for t in required if t not in proposed]
        removed = [t for t in proposed if t not in required]
        if added or removed:
            run.emit("plan.corrected", "plan", reason="rule_check", added=added, removed=removed)

    cond = state["conditions"]
    query = {"region": cond.get("region"), "genre": cond.get("genre"), "keyword": state.get("keyword"),
             "limit": 5 if state["intent"] == "fact_query" else 20}
    tasks = _tasks(state, required, query, run)
    run.emit("plan.created", "plan", plan_version=0, strategy="initial", tasks=tasks)
    _send_tasks(run, 0, "initial", tasks)
    return {"tasks": tasks, "query": query, "plan_version": 0, "strategy_index": 0, "replan_count": 0,
            "replanning": False, "phase": "collect", "relaxed": [], "replan_reasons": [], "route_after_plan": "execute"}


def _rebuild(state: PlannerState, run: RunContext) -> dict[str, Any]:
    """검증(로깅 Agent)이 이상으로 판정 → 작업 목록 재구성: Worker 의 LLM 재시도를 중단하고 확보한 결과로 판단 진행."""
    rules = ", ".join(sorted({w["rule"] for w in state["verification"].get("warnings", [])}))
    reason = f"검증 이상({rules}) → Worker 재시도 중단, 확보한 결과로 판단"
    tasks = [{**t, "retry": False} for t in state["tasks"]]
    run.emit("plan.created", "plan", plan_version=state.get("plan_version", 0), strategy="verified_rebuild",
             reason=reason, tasks=tasks)
    _send_tasks(run, state.get("plan_version", 0), "verified_rebuild", tasks)
    return {"tasks": tasks, "rebuild_requested": False, "rebuilt": True, "worker_retry_disabled": True,
            "route_after_plan": "judge"}


def _replan(state: PlannerState, run: RunContext) -> dict[str, Any]:
    query = dict(state["query"])
    found = next_strategy(query, state.get("strategy_index", 0), skip_for(state))
    assert found is not None, "judge 가 적용 가능한 전략이 있을 때만 재계획을 요청한다"
    index, strategy = found
    relaxed = list(state.get("relaxed", []))
    if strategy == "expand_pool":
        query["limit"] = EXPANDED_LIMIT
    elif strategy == "drop_genre":
        relaxed.append({"field": "genre", "from": query["genre"]})
        query["genre"] = None
    elif strategy == "widen_region":
        relaxed.append({"field": "region", "from": query["region"], "to": "서울"})
        query["region"] = "서울"
    count = state.get("replan_count", 0) + 1
    reason = (state.get("replan_reasons") or ["충족 후보 0개"])[-1]
    run.emit("replan", "plan", count=count, strategy=strategy, reason=reason)
    tools = [t["tool"] for t in state["tasks"]]
    tasks = _tasks(state, tools, query, run)
    run.emit("plan.created", "plan", plan_version=count, strategy=strategy, tasks=tasks)
    _send_tasks(run, count, strategy, tasks)
    return {"tasks": tasks, "query": query, "plan_version": count, "strategy_index": index, "replan_count": count,
            "replanning": False, "phase": "collect", "relaxed": relaxed, "route_after_plan": "execute"}
