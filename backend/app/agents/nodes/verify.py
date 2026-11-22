"""verify 노드 (F3021) — Worker 수행 결과의 검증은 로깅 Agent 가 담당한다.

로깅 Agent 의 inspect(run_id) 가 지금까지의 실행 이벤트를 규칙으로 판정(F3020)해 돌려준다.
이상이면 Planner 가 작업 목록을 재구성한다 (실행당 1회). LLM 없음.
"""
from __future__ import annotations

from typing import Any

from ..runtime import RunContext
from ..state import PlannerState


def verify(state: PlannerState, run: RunContext) -> dict[str, Any]:
    verifier = run.deps.verifier
    if verifier is None:
        report = {"verdict": "undeterminable", "warnings": [], "reason": "검증기(로깅 Agent) 미연결"}
    else:
        try:
            report = verifier(run.run_id)
        except Exception as e:  # noqa: BLE001
            report = {"verdict": "undeterminable", "warnings": [], "reason": f"검증 실패({type(e).__name__})"}
    summary = {"verdict": report["verdict"], "warnings": report.get("warnings", []), "reason": report.get("reason")}
    run.emit("verify.result", "verify", **summary)
    run.message("verify", "LoggingAgent", "Planner", "verification",
                {"verdict": summary["verdict"], "warnings": summary["warnings"]})
    rebuild = summary["verdict"] == "anomaly" and not state.get("rebuilt")
    return {"verification": summary, "rebuild_requested": rebuild}
