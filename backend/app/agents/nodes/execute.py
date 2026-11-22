"""execute 노드 — F3007 Tool 호출·결과 통합. LLM 없음.

collect: 후보 조회 → (아직 안 본) 후보 상세 조회. 앞 Tool 결과가 다음 Tool 입력.
enrich : 추천이 확정된 공연장에만 주변 장소 조회.
실패는 사유를 남기고 계속 진행. 치명적 실패(키 누락·인증·한도)만 흐름을 멈춘다.
"""
from __future__ import annotations

from typing import Any

from ...tools.base import FATAL, ErrorCode
from ..runtime import RunContext
from ..state import DETAIL, NEARBY, SEARCH, PlannerState


def execute(state: PlannerState, run: RunContext) -> dict[str, Any]:
    if state.get("phase") == "enrich":
        return _enrich(state, run)
    return _collect(state, run)


def _collect(state: PlannerState, run: RunContext) -> dict[str, Any]:
    deps = run.deps
    cache = dict(state.get("tool_cache", {}))
    seen = list(state.get("seen_ids", []))
    details = dict(state.get("details", {}))
    failures = list(state.get("tool_failures", []))
    notices = list(state.get("notices", []))
    tasks = state["tasks"]
    update: dict[str, Any] = {}

    search = next((t for t in tasks if t["tool"] == SEARCH), None)
    if search:
        r = run.call_tool(cache, "execute", SEARCH, search["args"])
        if not r.ok:
            if r.error.code in FATAL:
                return {"tool_cache": cache, "stop_reason": f"fatal:{r.error.code.value}", "round_ids": [],
                        "tool_failures": failures + [{"tool": SEARCH, "target": None, "code": r.error.code.value}]}
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

    for pid in new_ids:
        seen.append(pid)
        r = run.call_tool(cache, "execute", DETAIL, {"performance_id": pid})
        details[pid] = r.model_dump()
        if not r.ok and r.error.code != ErrorCode.NO_RUNTIME:      # 러닝타임 없음은 '판단 불가' 데이터, 실패 아님
            failures.append({"tool": DETAIL, "target": pid, "code": r.error.code.value})
            if r.error.code in FATAL:
                update["stop_reason"] = f"fatal:{r.error.code.value}"
                break

    return {"tool_cache": cache, "seen_ids": seen, "round_ids": new_ids, "details": details,
            "tool_failures": failures, "notices": notices, **update}


def _enrich(state: PlannerState, run: RunContext) -> dict[str, Any]:
    cache = dict(state.get("tool_cache", {}))
    failures = list(state.get("tool_failures", []))
    notices = list(state.get("notices", []))
    places: dict[str, list[dict]] = dict(state.get("places", {}))
    places_failed: list[str] = list(state.get("places_failed", []))
    category = state["conditions"].get("place_category")
    venues = list(dict.fromkeys(e["venue_id"] for e in state.get("eligible", [])[: run.deps.max_enrich] if e.get("venue_id")))
    for venue_id in venues:
        r = run.call_tool(cache, "execute", NEARBY, {"venue_id": venue_id, "category": category})
        if r.ok:
            places[venue_id] = r.data["places"]
        else:
            places[venue_id] = []
            if r.error.code != ErrorCode.NO_RESULT:
                failures.append({"tool": NEARBY, "target": venue_id, "code": r.error.code.value})
                places_failed.append(venue_id)
            if r.error.code == ErrorCode.MISSING_API_KEY and not any(n["type"] == "config" for n in notices):
                notices.append({"type": "config", "message": "카카오 API 키가 없어 주변 장소는 안내하지 못했습니다."})
    return {"tool_cache": cache, "places": places, "places_failed": places_failed, "tool_failures": failures,
            "notices": notices, "phase": "done"}
