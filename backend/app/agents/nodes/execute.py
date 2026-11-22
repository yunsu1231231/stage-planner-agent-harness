"""execute 노드 — F3007 Tool 호출·결과 통합 (baseline) / F3021 Worker (planner_worker).

collect: 후보 조회 → (아직 안 본) 후보 상세 조회. 앞 Tool 결과가 다음 Tool 입력.
enrich : 추천이 확정된 공연장에만 주변 장소 조회.
실패는 사유를 남기고 계속 진행. 치명적 실패(키 누락·인증·한도)만 흐름을 멈춘다.
planner_worker 모드에서는 각 작업을 worker.run_task 로 수행하고(규칙 분류 → 필요할 때만 LLM 재시도),
수행 결과를 정해진 형식(work_result)으로 Planner 에 보고한다.
"""
from __future__ import annotations

from typing import Any, Callable

from ...tools.base import FATAL, ErrorCode, ToolResult
from ..runtime import RunContext
from ..state import DETAIL, NEARBY, SEARCH, PlannerState
from ..worker import run_task

Invoke = Callable[[str, dict, list, str], tuple[ToolResult, dict]]


def _invoker(state: PlannerState, run: RunContext, cache: dict) -> Invoke:
    if run.deps.mode == "planner_worker":
        disabled = bool(state.get("worker_retry_disabled"))
        return lambda tool, args, fixed, tid: run_task(run, cache, tool, args, fixed, tid, retry_disabled=disabled)

    def baseline(tool, args, fixed, tid):
        r = run.call_tool(cache, "execute", tool, args)
        return r, {"action": "done" if r.ok else "baseline"}
    return baseline


def _report(run: RunContext, outcomes: list[tuple[str, str, ToolResult, dict]], replan_requests: list[dict]) -> None:
    if run.deps.mode != "planner_worker":
        return
    run.message("execute", "Worker", "Planner", "work_result", {
        "done": sum(1 for *_, r, o in outcomes if r.ok),
        "failed": sum(1 for *_, r, o in outcomes if not r.ok and o["action"] != "data_gap"),
        "retried": sum(1 for *_, o in outcomes if o.get("attempts")),
        "unresolved": [{"task_id": tid, "tool": tool, "code": r.error.code.value, "action": o["action"]}
                       for tid, tool, r, o in outcomes if not r.ok and o["action"] != "data_gap"],
        "replan_requests": replan_requests})


def execute(state: PlannerState, run: RunContext) -> dict[str, Any]:
    if state.get("phase") == "enrich":
        return _enrich(state, run)
    return _collect(state, run)


def _collect(state: PlannerState, run: RunContext) -> dict[str, Any]:
    deps = run.deps
    cache = dict(state.get("tool_cache", {}))
    invoke = _invoker(state, run, cache)
    seen = list(state.get("seen_ids", []))
    details = dict(state.get("details", {}))
    failures = list(state.get("tool_failures", []))
    notices = list(state.get("notices", []))
    tasks = state["tasks"]
    outcomes: list[tuple[str, str, ToolResult, dict]] = []
    replan_requests: list[dict] = []
    update: dict[str, Any] = {}

    search = next((t for t in tasks if t["tool"] == SEARCH), None)
    if search:
        r, o = invoke(SEARCH, search["args"], search.get("fixed_args", []), search["id"])
        outcomes.append((search["id"], SEARCH, r, o))
        if not r.ok:
            if r.error.code in FATAL or o["action"] in ("fatal", "missing_arg"):
                code = r.error.code.value if r.error.code in FATAL else "MISSING_ARGUMENT"
                failures.append({"tool": SEARCH, "target": None, "code": r.error.code.value})
                _report(run, outcomes, replan_requests)
                return {"tool_cache": cache, "stop_reason": f"fatal:{code}", "round_ids": [],
                        "tool_failures": failures, "replan_requests": replan_requests}
            if o["action"] == "replan_request":
                replan_requests.append({"tool": SEARCH, "code": r.error.code.value, "task_id": search["id"]})
            if r.error.code != ErrorCode.NO_RESULT:
                failures.append({"tool": SEARCH, "target": None, "code": r.error.code.value})
            items = []
        else:
            items = r.data["items"]
            if r.meta.get("estimated") and not any(n.get("type") == "estimated" for n in notices):
                notices.append({"type": "estimated", "message": r.meta["note"]})
        limit = 1 if state["intent"] == "fact_query" else deps.max_detail
        new_ids = [i["performance_id"] for i in items if i["performance_id"] not in seen][:limit]
    else:
        new_ids = [t["args"]["performance_id"] for t in tasks if t["tool"] == DETAIL]

    detail_task = next((t for t in tasks if t["tool"] == DETAIL), {"id": "detail"})
    for pid in new_ids:
        seen.append(pid)
        r, o = invoke(DETAIL, {"performance_id": pid}, ["performance_id"], f"{detail_task['id']}:{pid}")
        outcomes.append((f"{detail_task['id']}:{pid}", DETAIL, r, o))
        details[pid] = r.model_dump()
        if not r.ok and r.error.code != ErrorCode.NO_RUNTIME:      # 러닝타임 없음은 '판단 불가' 데이터, 실패 아님
            failures.append({"tool": DETAIL, "target": pid, "code": r.error.code.value})
            if r.error.code in FATAL:
                update["stop_reason"] = f"fatal:{r.error.code.value}"
                break

    _report(run, outcomes, replan_requests)
    return {"tool_cache": cache, "seen_ids": seen, "round_ids": new_ids, "details": details,
            "tool_failures": failures, "notices": notices, "replan_requests": replan_requests, **update}


def _enrich(state: PlannerState, run: RunContext) -> dict[str, Any]:
    cache = dict(state.get("tool_cache", {}))
    invoke = _invoker(state, run, cache)
    failures = list(state.get("tool_failures", []))
    notices = list(state.get("notices", []))
    places: dict[str, list[dict]] = dict(state.get("places", {}))
    places_failed: list[str] = list(state.get("places_failed", []))
    category = state["conditions"].get("place_category")
    task = next((t for t in state["tasks"] if t["tool"] == NEARBY), {"id": "nearby"})
    outcomes: list[tuple[str, str, ToolResult, dict]] = []
    venues = list(dict.fromkeys(e["venue_id"] for e in state.get("eligible", [])[: run.deps.max_enrich] if e.get("venue_id")))
    for venue_id in venues:
        r, o = invoke(NEARBY, {"venue_id": venue_id, "category": category}, ["venue_id", "category"],
                      f"{task['id']}:{venue_id}")
        outcomes.append((f"{task['id']}:{venue_id}", NEARBY, r, o))
        if r.ok:
            places[venue_id] = r.data["places"]
        else:
            places[venue_id] = []
            if r.error.code != ErrorCode.NO_RESULT:
                failures.append({"tool": NEARBY, "target": venue_id, "code": r.error.code.value})
                places_failed.append(venue_id)
            if r.error.code == ErrorCode.MISSING_API_KEY and not any(n["type"] == "config" for n in notices):
                notices.append({"type": "config", "message": "카카오 API 키가 없어 주변 장소는 안내하지 못했습니다."})
    _report(run, outcomes, [])
    return {"tool_cache": cache, "places": places, "places_failed": places_failed, "tool_failures": failures,
            "notices": notices, "phase": "done"}
