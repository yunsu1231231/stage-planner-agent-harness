"""F3021 Worker — 작업 목록대로 Tool 을 호출하고, 실패는 규칙으로 분류한다 (docs/04 7A.2).

LLM 은 '인자를 고치면 결과가 달라질 수 있는 실패 + 고칠 수 있는 인자 있음'일 때만 묻는다.
치명적 실패·필수 인자 누락·재시도 무의미·고칠 인자 없음은 규칙으로 처리하고 LLM 을 부르지 않는다.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..tools.base import FATAL, RETRYABLE, ErrorCode, ToolResult
from .runtime import RunContext
from .state import DETAIL, NEARBY, SEARCH

# Tool 별로 Worker 가 바꿀 수 있는 인자 (Planner 고정 인자는 다시 제외). 날짜·지역·장르·ID·공연장·장소 종류는 없음.
TUNABLE_ORDER: dict[str, list[str]] = {SEARCH: ["keyword"], NEARBY: ["radius_m", "size"], DETAIL: []}
TUNABLE = {k: set(v) for k, v in TUNABLE_ORDER.items()}
_MUST_EXIST = {"keyword"}          # 검색어는 원래 있던 경우에만 고칠 수 있다 (없던 검색어를 지어내지 않음)

RULE_REASON = {"fatal": "치명적 실패 — 재시도해도 같음, 사용자 안내 필요",
               "missing_arg": "필수 인자 누락 — 되묻거나 멈출 일",
               "skip": "재시도 무의미하거나 고칠 인자 없음",
               "escalate": "고칠 수 있는 인자 없음 — Planner 에 계획 변경 요청"}

WORKER_SYSTEM = """너는 공연 플래너의 Worker 다. 방금 Tool 호출이 실패했다. 다음 중 하나를 고른다.
- retry: 고칠 수 있는 인자(tunable_args)만 바꿔 같은 Tool 로 다시 호출. 바꿀 값만 채운다.
- skip: 이 작업을 건너뛴다.
- replan_request: Planner 에게 계획 변경을 요청한다.
고정 인자(fixed_args)는 바꿀 수 없다. 같은 인자로 다시 시도하지 않는다. reason 에 한 문장으로 이유를 쓴다."""


class WorkerDecision(BaseModel):
    action: Literal["retry", "skip", "replan_request"]
    reason: str = Field(description="결정 이유 한 문장")
    keyword: str | None = Field(None, description="search_performances 검색어를 바꿀 때만")
    radius_m: int | None = Field(None, description="search_nearby_places 반경(미터, 최대 2000)을 바꿀 때만")
    size: int | None = Field(None, description="search_nearby_places 결과 수를 바꿀 때만")


def classify(tool: str, args: dict[str, Any], fixed_args: list[str], result: ToolResult) -> tuple[str, list[str]]:
    """→ (fatal | missing_arg | skip | escalate | ask_llm, 고칠 수 있는 인자)"""
    err = result.error
    if err.code in FATAL:
        return "fatal", []
    if err.code == ErrorCode.INVALID_INPUT and (err.detail or "").startswith("missing"):
        return "missing_arg", []
    if err.code not in RETRYABLE:
        return "skip", []
    tunable = [k for k in TUNABLE_ORDER.get(tool, []) if k not in fixed_args and (k not in _MUST_EXIST or k in args)]
    if not tunable:
        return ("escalate" if tool == SEARCH else "skip"), []
    return "ask_llm", tunable


def _give_up(tool: str) -> str:
    return "replan_request" if tool == SEARCH else "skip"


def run_task(run: RunContext, cache: dict, tool: str, args: dict[str, Any], fixed_args: list[str], task_id: str,
             retry_disabled: bool = False) -> tuple[ToolResult, dict[str, Any]]:
    deps = run.deps
    cur = dict(args)
    attempt = 0
    r = run.call_tool(cache, "execute", tool, cur, extra={"task_id": task_id, "attempt": 0})
    while not r.ok:
        code = r.error.code.value
        if r.error.code == ErrorCode.NO_RUNTIME:          # 실패가 아니라 '판단 불가' 데이터
            return r, {"action": "data_gap", "code": code, "attempts": attempt}
        kind, tunable = classify(tool, cur, fixed_args, r)
        base = {"task_id": task_id, "tool": tool, "code": code, "attempt": attempt, "fixed_args": fixed_args}

        if kind == "ask_llm" and (not deps.worker_llm or retry_disabled):
            reason = "worker_llm_off" if not deps.worker_llm else "retry_disabled_by_planner"
            run.emit("worker.decision", "execute", **base, action=_give_up(tool), llm=False, reason=reason)
            return r, {"action": _give_up(tool), "code": code, "attempts": attempt}
        if kind != "ask_llm":
            action = {"fatal": "fatal", "missing_arg": "missing_arg", "skip": "skip", "escalate": "replan_request"}[kind]
            run.emit("worker.decision", "execute", **base, action=action, llm=False, reason=RULE_REASON[kind])
            return r, {"action": action, "code": code, "attempts": attempt}
        if attempt >= deps.max_worker_retries:
            run.emit("worker.decision", "execute", **base, action=_give_up(tool), llm=False, reason="retry_limit")
            return r, {"action": _give_up(tool), "code": code, "attempts": attempt}

        run.llm_calls += 1
        run.worker_llm_calls += 1
        request = {"tool": tool, "args": cur, "fixed_args": fixed_args, "tunable_args": tunable,
                   "error": {"code": code, "message": r.error.message}, "attempt": attempt}
        try:
            d = deps.llm.with_structured_output(WorkerDecision).invoke(
                [SystemMessage(WORKER_SYSTEM), HumanMessage(json.dumps(request, ensure_ascii=False))])
            if isinstance(d, dict):
                d = WorkerDecision.model_validate(d)
        except Exception as e:  # noqa: BLE001
            run.emit("worker.decision", "execute", **base, action=_give_up(tool), llm=True, reason="llm_failed",
                     detail=type(e).__name__)
            return r, {"action": _give_up(tool), "code": code, "attempts": attempt}

        patch = {k: getattr(d, k) for k in ("keyword", "radius_m", "size") if getattr(d, k) is not None}
        if d.action != "retry":
            run.emit("worker.decision", "execute", **base, action=d.action, llm=True, reason=d.reason)
            return r, {"action": d.action, "code": code, "attempts": attempt}
        rejected = ("not_tunable" if any(k not in tunable for k in patch)
                    else "identical" if not patch or all(cur.get(k) == v for k, v in patch.items()) else None)
        if rejected:                                       # 규칙 검증: 고정·허용 외 인자, 같은 인자 재시도 금지
            run.emit("worker.decision", "execute", **base, action=_give_up(tool), llm=True, reason=d.reason,
                     patch=patch, rejected=rejected)
            return r, {"action": _give_up(tool), "code": code, "attempts": attempt}

        run.emit("worker.decision", "execute", **base, action="retry", llm=True, reason=d.reason, patch=patch)
        cur.update(patch)
        attempt += 1
        r = run.call_tool(cache, "execute", tool, cur, extra={"task_id": task_id, "attempt": attempt, "retry_of": task_id})
    return r, {"action": "done", "attempts": attempt, "args": cur}
