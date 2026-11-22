"""F3020 이상 징후 판정 — 규칙만 (LLM 금지 구역, 가드 테스트가 import 를 감시). docs/04 7A.1

이벤트를 대조하고 횟수를 센다. 근거가 되는 이벤트가 없으면 '이상 없음'이 아니라 '판정 불가'.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

RULES = ("repeated_call", "excessive_replan", "unplanned_call")


def evaluate_run(events: list[dict[str, Any]], replan_limit: int = 3, final: bool = True) -> dict[str, Any]:
    """→ {run_id, verdict: normal|anomaly|undeterminable, final, checked: {rule: ok|warning|undeterminable},
          warnings: [{rule, detail, evidence_seqs}], event_count}"""
    run_id = events[0].get("run_id") if events else None
    report: dict[str, Any] = {"run_id": run_id, "final": final, "event_count": len(events), "warnings": [],
                              "checked": {}}
    if not events or (final and not any(e["type"] == "run.end" for e in events)):
        report["checked"] = {r: "undeterminable" for r in RULES}
        report["verdict"] = "undeterminable"
        report["reason"] = "근거 이벤트 없음" if not events else "실행 종료(run.end) 이벤트 없음"
        return report

    requests = [e for e in events if e["type"] == "tool.request"]

    # 1) 같은 Tool·같은 인자 실제 호출(캐시 제외) 반복
    seen: dict[str, list[int]] = defaultdict(list)
    for e in requests:
        p = e.get("payload", {})
        if not p.get("cached"):
            seen[f"{p.get('tool')}:{json.dumps(p.get('args', {}), sort_keys=True, ensure_ascii=False)}"].append(e["seq"])
    repeated = {k: v for k, v in seen.items() if len(v) >= 2}
    for key, seqs in repeated.items():
        report["warnings"].append({"rule": "repeated_call", "detail": f"같은 입력으로 {len(seqs)}회 호출: {key}",
                                   "evidence_seqs": seqs})
    report["checked"]["repeated_call"] = "warning" if repeated else "ok"

    # 2) 재계획 과다
    replans = [e["seq"] for e in events if e["type"] == "replan"]
    if len(replans) >= replan_limit:
        report["warnings"].append({"rule": "excessive_replan", "detail": f"재계획 {len(replans)}회 (상한 {replan_limit})",
                                   "evidence_seqs": replans})
    report["checked"]["excessive_replan"] = "warning" if len(replans) >= replan_limit else "ok"

    # 3) 계획에 없던 Tool 호출 (직전 작업 목록 기준)
    active: set[str] | None = None
    unplanned: list[dict[str, Any]] = []
    for e in events:
        if e["type"] == "plan.created":
            active = {t.get("tool") for t in e.get("payload", {}).get("tasks", [])}
        elif e["type"] == "tool.request":
            if active is None:
                report["checked"]["unplanned_call"] = "undeterminable"
                break
            if e["payload"].get("tool") not in active:
                unplanned.append(e)
    if "unplanned_call" not in report["checked"]:
        for e in unplanned:
            report["warnings"].append({"rule": "unplanned_call", "detail": f"작업 목록에 없는 Tool: {e['payload'].get('tool')}",
                                       "evidence_seqs": [e["seq"]]})
        report["checked"]["unplanned_call"] = "warning" if unplanned else "ok"

    if report["warnings"]:
        report["verdict"] = "anomaly"
    elif "undeterminable" in report["checked"].values():
        report["verdict"] = "undeterminable"
    else:
        report["verdict"] = "normal"
    return report
