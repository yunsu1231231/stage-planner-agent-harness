"""F3021 구조 변경 전후 비교 — baseline vs Planner·Worker(Worker LLM on/off). 실제 LLM + 실제 API.

비교 지표: 실행 흐름, 재계획 횟수, 요청당 LLM 호출 수(그중 Worker), 응답 시간, 실제 Tool 호출 수,
검증(로깅 Agent) 판정. 실행: .venv/Scripts/python scripts/verification/compare_architectures.py
산출물: docs/verification/pw_comparison.json, pw_comparison.md, logs/compare_<config>_<scenario>.json
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.app import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402

OUT = ROOT / "docs" / "verification"
DATA = ROOT / "data" / "compare"

CONFIGS = [
    ("baseline", {"agent_mode": "baseline", "worker_llm": True}),
    ("pw_llm_on", {"agent_mode": "planner_worker", "worker_llm": True}),
    ("pw_llm_off", {"agent_mode": "planner_worker", "worker_llm": False}),
]
SCENARIOS = [
    ("C1", "정상 경로", "이번 토요일 오후 2시 이후에 대학로에서 5만원 이하 연극 보고 6시 전에는 끝내고 싶어. 끝나고 갈 식당도 알려줘"),
    ("C2", "재계획 후 성공", "11월 29일 일요일 저녁 7시 이후에 시작해서 9시 반 전에 끝나는 3만원 이하 대학로 뮤지컬 찾아줘"),
    ("C3", "재계획 상한", "다음 주 수요일 오전 9시 이후에 시작해서 오전 11시 전에 끝나는 대학로 연극 있어?"),
    ("C4", "공연명 오타 (Worker 인자 수정)", "여신님 보고계셔 러닝타임이 몇 분이야?"),
    # 1차 실행의 '서커스'는 실제로 3건 있어 후보 0건 상황이 아니었음 → 실호출로 0건 확인한 '대중무용'으로 교체
    ("C5", "후보 0건 장르 (Worker 계획 변경 요청)", "11월 28일 토요일 저녁 6시 이후 대학로에서 대중무용 공연 보고 싶어. 9시 전에 끝나야 해"),
]


def summarize(res: dict, log: list[dict], report: dict | None) -> dict:
    steps = [e["node"] for e in log if e["type"] == "node.enter"]
    real_calls = [e["payload"]["tool"] for e in log if e["type"] == "tool.request" and not e["payload"].get("cached")]
    decisions = [e["payload"] for e in log if e["type"] == "worker.decision"]
    return {
        "status": res["status"], "replan_count": res["replan_count"], "llm_calls": res["llm_calls"],
        "worker_llm_calls": res.get("worker_llm_calls", 0),
        "duration_ms": next((e["payload"]["duration_ms"] for e in log if e["type"] == "run.end"), None),
        "real_tool_calls": len(real_calls),
        "tool_calls_by_name": {t: real_calls.count(t) for t in sorted(set(real_calls))},
        "strategies": [e["payload"]["strategy"] for e in log if e["type"] == "replan"],
        "replan_reasons": [e["payload"]["reason"] for e in log if e["type"] == "replan"],
        "steps": steps,
        "worker_decisions": [{k: d.get(k) for k in ("tool", "code", "action", "llm", "reason", "patch", "rejected")}
                             for d in decisions],
        "verify": [e["payload"]["verdict"] for e in log if e["type"] == "verify.result"],
        "messages": sum(e["type"] == "agent.message" for e in log),
        "final_verdict": report["verdict"] if report else None,
        "final_warnings": [w["rule"] for w in (report or {}).get("warnings", [])],
        "diagnosis": (report or {}).get("diagnosis", {}) and report["diagnosis"]["text"],
        "recommendations": [r["title"] for r in res.get("recommendations", [])],
        "facts": (res.get("facts") or {}).get("title"),
        "reply_head": res["reply"][:160],
    }


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    for f in DATA.glob("*.db*"):
        f.unlink()
    base = Settings.from_env()
    results: dict[str, dict[str, dict]] = {}
    for cname, over in CONFIGS:
        app = create_app(settings=replace(base, **over), db_path=DATA / f"{cname}.db")
        app.state.logging_agent.run_async = False          # 진단까지 끝난 뒤 보고서를 읽기 위해
        client = TestClient(app)
        results[cname] = {}
        for sid, _, msg in SCENARIOS:
            session = f"cmp-{cname}-{sid}"
            res = client.post("/api/chat", json={"session_id": session, "message": msg}).json()
            log = client.get(f"/api/logs/{session}", params={"run_id": res["run_id"]}).json()["events"]
            reports = client.get(f"/api/logs/{session}/anomalies").json()["reports"]
            report = next((r for r in reports if r["run_id"] == res["run_id"]), None)
            (OUT / "logs" / f"compare_{cname}_{sid}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1),
                                                                     encoding="utf-8")
            s = summarize(res, log, report)
            results[cname][sid] = s
            print(f"{cname:10s} {sid} {s['status']:14s} replan={s['replan_count']} llm={s['llm_calls']} "
                  f"(worker {s['worker_llm_calls']}) tools={s['real_tool_calls']} {s['duration_ms']}ms "
                  f"strategies={s['strategies']} verdict={s['final_verdict']}")
        client.close()
        app.state.plans.db.close()

    (OUT / "pw_comparison.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                                                        "model": base.llm_model, "configs": [c for c, _ in CONFIGS],
                                                        "scenarios": SCENARIOS, "results": results},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(results, base.llm_model)


def write_md(results: dict, model: str) -> None:
    names = {"baseline": "baseline (필수 구조)", "pw_llm_on": "Planner·Worker · Worker LLM ON", "pw_llm_off": "Planner·Worker · Worker LLM OFF"}
    L = [f"# Planner·Worker 구조 전후 비교 (F3021)\n",
         f"- 생성 {datetime.now().isoformat(timespec='seconds')} · 모델 `{model}` · 실제 KOPIS·카카오 API · 시나리오 5 × 구성 3",
         "- 실행: `.venv/Scripts/python scripts/verification/compare_architectures.py` · 원본 `pw_comparison.json`, `logs/compare_*.json`\n",
         "## 1. 요약 (요청당 평균)\n", "| 구성 | LLM 호출 | 그중 Worker | 재계획 합계 | 실제 Tool 호출 | 응답 시간 |", "|---|---|---|---|---|---|"]
    for c, rs in results.items():
        v = list(rs.values())
        L.append(f"| {names[c]} | {mean(x['llm_calls'] for x in v):.1f} | {mean(x['worker_llm_calls'] for x in v):.1f} | "
                 f"{sum(x['replan_count'] for x in v)} | {mean(x['real_tool_calls'] for x in v):.1f} | "
                 f"{mean(x['duration_ms'] for x in v) / 1000:.1f}초 |")
    L += ["\n## 2. 시나리오별\n"]
    for sid, title, msg in SCENARIOS:
        L += [f"### {sid}. {title}\n", f"요청: {msg}\n",
              "| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |", "|---|---|---|---|---|---|---|---|"]
        for c in results:
            x = results[c][sid]
            outcome = x["facts"] or (", ".join(x["recommendations"][:2]) if x["recommendations"] else "-")
            L.append(f"| {names[c]} | `{x['status']}` | {x['replan_count']} ({' → '.join(x['strategies']) or '-'}) | "
                     f"{x['llm_calls']} ({x['worker_llm_calls']}) | {x['real_tool_calls']} | {x['duration_ms'] / 1000:.1f}초 | "
                     f"{'/'.join(x['verify']) or '-'} · {x['final_verdict']}{' ' + str(x['final_warnings']) if x['final_warnings'] else ''} | {outcome[:40]} |")
        for c in results:
            x = results[c][sid]
            for d in x["worker_decisions"]:
                L.append(f"- {names[c]} Worker 판단: `{d['action']}` ({'LLM' if d['llm'] else '규칙'}) {d['tool']} {d['code']}"
                         f"{' patch=' + json.dumps(d['patch'], ensure_ascii=False) if d.get('patch') else ''}"
                         f"{' 거부=' + d['rejected'] if d.get('rejected') else ''} — {d['reason']}")
            for r in x["replan_reasons"]:
                if "Worker" in r:
                    L.append(f"- {names[c]} 재계획 사유: {r}")
            if x["diagnosis"]:
                L.append(f"- {names[c]} 로깅 Agent 진단(LLM): {x['diagnosis']}")
        L.append("")
    L += ["## 3. 실행 흐름 예 (C4)\n"]
    for c in results:
        L.append(f"- **{names[c]}**: {' → '.join(results[c]['C4']['steps'])}")
    (OUT / "pw_comparison.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
