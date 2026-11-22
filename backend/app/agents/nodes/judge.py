"""judge 노드 — F3008 제약 판단 + F3009 재계획 결정. LLM 없음."""
from __future__ import annotations

from typing import Any

from ..judge import evaluate, suggest_adjustments
from ..runtime import RunContext
from ..state import NEARBY, PlannerState
from .plan import next_strategy


def judge(state: PlannerState, run: RunContext) -> dict[str, Any]:
    if state.get("stop_reason") or state["intent"] == "fact_query":
        return {"next": "respond"}

    cond, details = state["conditions"], state.get("details", {})
    evaluations = list(state.get("evaluations", []))
    evaluations += [evaluate(pid, details[pid], cond) for pid in state.get("round_ids", [])]
    eligible = sorted((e for e in evaluations if e["result"] == "eligible"),
                      key=lambda e: (e["start_time"], e.get("min_price") or 0))
    counts = {k: sum(e["result"] == k for e in evaluations) for k in ("eligible", "excluded", "unjudgeable")}
    run.emit("judge.result", "judge", plan_version=state.get("plan_version", 0), **counts)
    update: dict[str, Any] = {"evaluations": evaluations, "eligible": eligible}

    if eligible:
        wants_places = any(t["tool"] == NEARBY for t in state["tasks"])
        return {**update, "next": "enrich" if wants_places else "respond",
                "phase": "enrich" if wants_places else "done"}

    count = state.get("replan_count", 0)
    if count < run.deps.max_replan and next_strategy(state["query"], state.get("strategy_index", 0)):
        reasons = list(state.get("replan_reasons", [])) + [
            f"충족 후보 0개 (제외 {counts['excluded']}, 판단 불가 {counts['unjudgeable']})"]
        return {**update, "next": "replan", "replanning": True, "replan_reasons": reasons}

    ok_details = [d["data"] for d in details.values() if d.get("ok")]
    return {**update, "next": "respond", "stop_reason": "limit_reached" if count >= run.deps.max_replan else "no_match",
            "suggestions": suggest_adjustments(ok_details, cond)}
