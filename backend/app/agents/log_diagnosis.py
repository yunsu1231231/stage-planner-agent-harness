"""F3020 원인 진단 — 로깅 Agent 에 주입되는 LLM 함수. 이상(anomaly)으로 판정된 실행에만 호출된다.

로깅 Agent 의 수집·저장 코드(logging_agent.py)는 LLM 을 import 하지 않는다. LLM 은 이 모듈에만 있다.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

DIAGNOSIS_SYSTEM = """너는 Agent 실행 기록을 점검하는 로깅 Agent 다. 규칙 판정에서 경고가 나온 실행의 원인을 진단한다.
- 세 문장 이내 한국어.
- 어느 Agent(Planner / Worker / 로깅) 쪽 문제인지, 무엇을 고치면 되는지 말한다.
- 기록에 없는 사실을 만들지 않는다."""

_KEEP = ("seq", "type", "node", "payload")


def _compact(events: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    out = []
    for e in events[-limit:]:
        p = dict(e.get("payload") or {})
        p.pop("tasks", None) if e.get("type") != "plan.created" else None
        out.append({k: (p if k == "payload" else e.get(k)) for k in _KEEP})
    return out


def make_diagnoser(llm: Any) -> Callable[[list[dict[str, Any]], dict[str, Any]], str]:
    def diagnose(events: list[dict[str, Any]], report: dict[str, Any]) -> str:
        body = {"warnings": report["warnings"], "events": _compact(events)}
        msg = llm.invoke([SystemMessage(DIAGNOSIS_SYSTEM),
                          HumanMessage(json.dumps(body, ensure_ascii=False, default=str))])
        return str(msg.content).strip()
    return diagnose
