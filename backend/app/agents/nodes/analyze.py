"""analyze 노드 — F3005 요청 분석 + F3010 맥락 병합. LLM 1회(structured output)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..judge import weekday_ko
from ..memory import merge_conditions
from ..prompts import ANALYZE_SYSTEM, AnalyzeOutput
from ..runtime import RunContext
from ..state import PLAN_INTENTS, PlannerState

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate(out: AnalyzeOutput, today: date) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """형식이 틀리거나 쓸 수 없는 값은 버린다 (임의 보정 금지)."""
    delta: dict[str, Any] = {}
    notices: list[dict[str, str]] = []
    if out.date:
        try:
            d = date.fromisoformat(out.date)
            if d < today:
                notices.append({"type": "invalid", "message": f"{out.date}는 지난 날짜라 사용하지 않았습니다."})
            else:
                delta["date"] = out.date
        except ValueError:
            notices.append({"type": "invalid", "message": f"날짜 '{out.date}'를 이해하지 못했습니다."})
    for k in ("earliest_start", "end_by"):
        v = getattr(out, k)
        if v is not None:
            if _HHMM.match(v):
                delta[k] = v
            else:
                notices.append({"type": "invalid", "message": f"시각 '{v}'를 이해하지 못했습니다."})
    if out.budget_max is not None and out.budget_max > 0:
        delta["budget_max"] = out.budget_max
    if out.age is not None and 0 <= out.age <= 120:
        delta["age"] = out.age
    for k in ("region", "genre", "place_category"):
        if getattr(out, k):
            delta[k] = getattr(out, k)
    return delta, notices


def _missing(intent: str, cond: dict[str, Any], out: AnalyzeOutput, recs: list[dict]) -> tuple[list[str], int | None]:
    target = out.target_index
    if intent in PLAN_INTENTS:
        missing = [] if cond.get("date") else ["date"]
        if cond.get("end_by") and not cond.get("earliest_start"):
            missing.append("earliest_start")      # 계산할 시작점이 없음 (명세 2.2 예)
        return missing, target
    if intent == "fact_query":
        ok_target = target is not None and 1 <= target <= len(recs)
        return ([] if out.keyword or ok_target else ["keyword"]), target
    if intent == "confirm_plan":
        if not recs:
            return ["recommendation"], target
        if target is None and len(recs) == 1:
            return [], 1
        return ([] if target is not None and 1 <= target <= len(recs) else ["target_index"]), target
    return [], target


def analyze(state: PlannerState, run: RunContext) -> dict[str, Any]:
    deps, mem = run.deps, run.memory
    today = deps.today()
    messages = [SystemMessage(ANALYZE_SYSTEM.format(today=today.isoformat(), weekday=weekday_ko(today.isoformat()))),
                HumanMessage(f"이전 맥락:\n{mem.summary()}\n\n사용자 발화: {state['user_message']}")]
    run.llm_calls += 1
    try:
        out = deps.llm.with_structured_output(AnalyzeOutput).invoke(messages)
        if isinstance(out, dict):
            out = AnalyzeOutput.model_validate(out)
    except Exception as e:  # noqa: BLE001
        run.emit("error", "analyze", code="LLM_FAILED", detail=type(e).__name__)
        return {"stop_reason": "analyze_failed", "intent": "unknown", "conditions": dict(mem.conditions),
                "condition_sources": {k: "memory" for k in mem.conditions}, "missing": [], "notices": []}

    run.emit("llm.decision", "analyze", decision=out.intent, reason=out.reason)
    delta, notices = _validate(out, today)
    if out.intent in PLAN_INTENTS:
        conditions, sources = merge_conditions(mem.conditions, delta, reset=out.reset)
    else:
        conditions, sources = dict(mem.conditions), {k: "memory" for k in mem.conditions}
    missing, target = _missing(out.intent, conditions, out, mem.last_recommendations)
    return {"intent": out.intent, "intent_reason": out.reason, "conditions": conditions,
            "condition_sources": sources, "missing": missing, "notices": notices,
            "keyword": out.keyword, "target_index": target}
