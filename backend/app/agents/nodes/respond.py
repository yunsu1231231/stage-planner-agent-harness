"""respond 노드 — F3011 최종 응답. 구조화 결과(payload)는 코드가 만들고, LLM은 그것을 문장으로만 옮긴다."""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..memory import COND_KEYS
from ..prompts import CHAT_SYSTEM, RESPOND_SYSTEM
from ..runtime import RunContext
from ..state import PlannerState

MISSING_TEXT = {"date": "관람 날짜", "earliest_start": "몇 시 이후에 시작하면 좋을지",
                "keyword": "궁금한 공연 이름", "target_index": "저장할 추천 번호",
                "recommendation": "먼저 공연 추천"}
FIELD_TEXT = {"genre": "장르", "region": "지역"}
CONFIG_TEXT = {"MISSING_API_KEY": "공연 정보(KOPIS) API 키가 설정되지 않았습니다. .env 의 KOPIS_API_KEY 를 확인해 주세요.",
               "AUTH_FAILED": "공연 정보(KOPIS) API 키가 유효하지 않습니다. 키를 다시 확인해 주세요.",
               "RATE_LIMITED": "공연 정보 서비스 호출 한도를 넘었습니다. 잠시 후 다시 시도해 주세요."}


def _conditions_view(state: PlannerState) -> dict[str, Any]:
    cond, src = state.get("conditions", {}), state.get("condition_sources", {})
    return {k: ({"value": cond[k], "source": src.get(k, "user")} if cond.get(k) is not None else None) for k in COND_KEYS}


def _llm_text(run: RunContext, system: str, content: str) -> str | None:
    run.llm_calls += 1
    try:
        return str(run.deps.llm.invoke([SystemMessage(system), HumanMessage(content)]).content)
    except Exception as e:  # noqa: BLE001
        run.emit("error", "respond", code="LLM_FAILED", detail=type(e).__name__)
        return None


def _template(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    if payload["recommendations"]:
        lines.append("조건에 맞는 공연입니다.")
        for i, r in enumerate(payload["recommendations"], 1):
            price = f"{r['min_price']:,}원" if r.get("min_price") is not None else "가격 확인 필요"
            lines.append(f"{i}. {r['title']} — {r['date']} {r['start_time']}~{r['end_time']} "
                         f"({r['runtime_min']}분, {price}) · {r.get('venue_name') or ''}")
            lines.append(f"   근거: {r['criteria']}")
    elif payload.get("facts"):
        f = payload["facts"]
        lines.append(f"{f['title']}: 러닝타임 {f['runtime_min']}분, 회차 {f.get('schedule_raw')}, 가격 {f.get('price_raw')}")
    else:
        lines.append("조건을 모두 만족하는 공연을 찾지 못했습니다.")
        lines += payload.get("suggestions", [])
    for e in (payload["excluded"] + payload["unjudgeable"])[:5]:
        lines.append(f"- 제외: {e.get('title')} ({e['reason']})")
    lines += [n["message"] for n in payload["notices"]]
    return "\n".join(lines)


def respond(state: PlannerState, run: RunContext) -> dict[str, Any]:
    base = {"intent": {"value": state.get("intent"), "reason": state.get("intent_reason")},
            "conditions": _conditions_view(state), "missing": state.get("missing", []),
            "notices": list(state.get("notices", [])), "recommendations": [], "excluded": [], "unjudgeable": [],
            "suggestions": [], "replan_count": state.get("replan_count", 0),
            "relaxed": [r["field"] for r in state.get("relaxed", [])], "tool_failures": state.get("tool_failures", []),
            "facts": None, "saved_plan": None}
    stop = state.get("stop_reason") or ""

    if stop == "analyze_failed":
        return {"response": {**base, "status": "error", "reply": "요청을 이해하지 못했어요. 다시 한 번 말씀해 주시겠어요?"}}
    if state.get("missing"):
        asks = ", ".join(MISSING_TEXT.get(m, m) for m in state["missing"])
        reply = (f"추천을 위해 {asks}을(를) 알려 주세요." if "recommendation" not in state["missing"]
                 else "저장할 추천이 아직 없어요. 먼저 공연 추천을 받아 주세요.")
        if base["notices"]:
            reply += " (" + " ".join(n["message"] for n in base["notices"]) + ")"
        return {"response": {**base, "status": "clarify", "reply": reply}}
    if state.get("intent") == "chitchat":
        reply = _llm_text(run, CHAT_SYSTEM, state["user_message"]) or \
            "공연 관람 플래너예요. 날짜와 희망 시간, 지역을 알려 주시면 실제 공연 중에서 골라 드릴게요."
        return {"response": {**base, "status": "chat", "reply": reply}}
    if state.get("intent") == "confirm_plan":
        return {"response": _confirm(state, run, base)}
    if stop.startswith("fatal:"):
        code = stop.split(":", 1)[1]
        status = "config_missing" if code == "MISSING_API_KEY" else "error"
        return {"response": {**base, "status": status, "reply": CONFIG_TEXT.get(code, "외부 서비스 오류로 처리하지 못했습니다.")}}

    payload = dict(base)
    if state.get("intent") == "fact_query":
        found = next((d["data"] for d in state.get("details", {}).values() if d.get("ok")), None)
        keys = ("performance_id", "title", "venue_name", "runtime_min", "schedule_raw", "price_raw", "age_limit",
                "start_date", "end_date")
        payload["facts"] = {k: found.get(k) for k in keys} if found else None
        status = "ok" if found else "no_match"
    else:
        places = state.get("places", {})
        payload["recommendations"] = [{**e, "places": places.get(e.get("venue_id"), [])}
                                      for e in state.get("eligible", [])[:3]]
        payload["excluded"] = [e for e in state.get("evaluations", []) if e["result"] == "excluded"]
        payload["unjudgeable"] = [e for e in state.get("evaluations", []) if e["result"] == "unjudgeable"]
        payload["suggestions"] = state.get("suggestions", [])
        for r in state.get("relaxed", []):
            payload["notices"].append({"type": "relaxed", "message": (
                f"'{r['from']}' {FIELD_TEXT[r['field']]} 조건으로는 맞는 공연이 없어 {FIELD_TEXT[r['field']]} 조건을 넓혀 찾았습니다.")})
        if state.get("tool_failures"):
            payload["notices"].append({"type": "partial", "message": "일부 정보 조회에 실패해 해당 후보는 제외했습니다."})
        if payload["recommendations"]:
            status = "partial" if state.get("tool_failures") else "ok"
        else:
            status = stop or "no_match"
            if status == "limit_reached":
                payload["notices"].append({"type": "limit", "message": (
                    f"조건을 {state.get('replan_count', 0)}번 넓혀 다시 찾았지만 맞는 공연이 없습니다. 조건을 조정해 보시겠어요?")})

    llm_view = {k: payload[k] for k in ("conditions", "recommendations", "notices", "suggestions", "facts")}
    llm_view["excluded"] = [{"title": e.get("title"), "reason": e["reason"]} for e in payload["excluded"] + payload["unjudgeable"]]
    reply = _llm_text(run, RESPOND_SYSTEM, json.dumps(llm_view, ensure_ascii=False)) or _template(payload)
    return {"response": {**payload, "status": status, "reply": reply}}


def _confirm(state: PlannerState, run: RunContext, base: dict[str, Any]) -> dict[str, Any]:
    rec = run.memory.last_recommendations[state["target_index"] - 1]
    plan = {"performance_id": rec["performance_id"], "title": rec["title"], "venue_name": rec.get("venue_name"),
            "date": rec["date"], "start_time": rec["start_time"], "end_time": rec["end_time"],
            "price": rec.get("min_price"), "memo": None, "source_session_id": run.session_id}
    if run.deps.save_plan is None:
        return {**base, "status": "error", "reply": "저장 기능이 아직 연결되지 않았습니다."}
    try:
        result = run.deps.save_plan(plan)
    except Exception as e:  # noqa: BLE001
        run.emit("error", "respond", code="SAVE_FAILED", detail=type(e).__name__)
        return {**base, "status": "error", "reply": "계획을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."}
    reply = f"'{plan['title']}' {plan['date']} {plan['start_time']}~{plan['end_time']} 관람 계획을 저장했어요."
    notices = list(base["notices"])
    if result.get("overlaps"):
        names = ", ".join(f"{o['title']}({o['start_time']}~{o['end_time']})" for o in result["overlaps"])
        notices.append({"type": "overlap", "message": f"같은 날 시간이 겹치는 계획이 있어요: {names}"})
        reply += " " + notices[-1]["message"]
    return {**base, "notices": notices, "status": "saved", "reply": reply, "saved_plan": result.get("plan")}
