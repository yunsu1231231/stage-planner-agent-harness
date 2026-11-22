"""명세 4.7 대표 시나리오 검증 — 실제 LLM + 실제 외부 API + FastAPI 앱 전체(로깅 Agent 포함).

요청마다 최종 응답, 실행 로그(단계·Tool 호출·재계획), 기대 vs 실제를 기록한다.
비용 발생(LLM 약 25회). 실행: .venv/Scripts/python scripts/verification/run_scenarios.py

산출물 (docs/verification/):
  scenarios.json         요청별 결과·검사 결과 (기계 판독)
  scenario_report.md     요청별 기록 (사람용, 07 검증 문서에 인용)
  logs/<ID>.json         실행 로그 원본 (로깅 Agent 가 저장한 그대로, 저장소에서 다시 읽음)
  tools.json             등록 Tool 명세 (명세 4.1)
  graph.md               LangGraph 구조 (mermaid, 명세 4.2)
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app.agents.graph import build_graph  # noqa: E402
from app.api.app import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402

OUT = ROOT / "docs" / "verification"
DATA = ROOT / "data" / "verification"
SEARCH, DETAIL, NEARBY = "search_performances", "get_performance_detail", "search_nearby_places"

S1_MSG = "이번 토요일 오후 2시 이후에 대학로에서 5만원 이하 연극 보고 6시 전에는 끝내고 싶어. 끝나고 갈 식당도 알려줘"


# ---------------------------------------------------------------- 검사 도우미
def tools_called(log: list[dict]) -> list[str]:
    return [e["payload"]["tool"] for e in log if e["type"] == "tool.response"]


def recs_within(res: dict, start: str, end: str, budget: int) -> bool:
    return all(r["start_time"] >= start and r["end_time"] <= end and (r["min_price"] or 0) <= budget
               for r in res["recommendations"])


Check = Callable[[dict, list[dict]], tuple[bool, str]]


def c(desc: str, fn: Callable[[dict, list[dict]], Any]) -> tuple[str, Check]:
    def run(res, log):
        try:
            v = fn(res, log)
            return (bool(v), "")
        except Exception as e:  # noqa: BLE001
            return (False, f"{type(e).__name__}")
    return desc, run


SCENARIOS: list[dict[str, Any]] = [
    {"id": "V1", "kind": "제약을 한 번에 충족", "app": "main", "session": "v-main", "message": S1_MSG,
     "expected": "조건 추출 → 공연 목록·상세 → 판단 → 추천 공연장 주변 식당. 재계획 없이 추천 1편 이상, 모두 14:00 이후 시작·18:00 전 종료·5만원 이하.",
     "checks": [c("status ok/partial", lambda r, l: r["status"] in ("ok", "partial")),
                c("재계획 0회", lambda r, l: r["replan_count"] == 0),
                c("추천 1편 이상", lambda r, l: len(r["recommendations"]) >= 1),
                c("추천이 모든 제약 충족", lambda r, l: recs_within(r, "14:00", "18:00", 50000)),
                c("세 Tool 모두 호출", lambda r, l: {SEARCH, DETAIL, NEARBY} <= set(tools_called(l))),
                c("추천마다 판단 근거·근거 Tool", lambda r, l: all(x["criteria"] and x["evidence"] for x in r["recommendations"])),
                c("LLM 3회", lambda r, l: r["llm_calls"] == 3)]},
    {"id": "V2", "kind": "재계획이 필요한 요청", "app": "main", "session": "v-replan",
     # run1 은 '이번 일요일'(=실행 당일)이었고, 지난 회차 제외 수정 후엔 저녁 회차가 모두 지나 상한 도달이 됨 → 날짜 명시
     "message": "11월 29일 일요일 저녁 7시 이후에 시작해서 9시 반 전에 끝나는 3만원 이하 대학로 뮤지컬 찾아줘",
     "expected": "뮤지컬은 대부분 3만원 초과 → 충족 0 → 후보 확장·장르 해제 순으로 재계획. 재계획 1회 이상, 완화한 조건을 응답에 명시. 이미 조회한 상세는 재조회하지 않음.",
     "checks": [c("재계획 1회 이상", lambda r, l: r["replan_count"] >= 1),
                c("재계획 상한(3) 이하", lambda r, l: r["replan_count"] <= 3),
                c("상세 조회 중복 없음", lambda r, l: len([e for e in l if e["type"] == "tool.request" and e["payload"]["tool"] == DETAIL])
                  == len({e["payload"]["args"]["performance_id"] for e in l if e["type"] == "tool.request" and e["payload"]["tool"] == DETAIL})),
                c("조건 완화 시 안내 포함", lambda r, l: not r["relaxed"] or any(n["type"] == "relaxed" for n in r["notices"])),
                c("오늘 관람이면 이미 시작한 회차 추천 없음 (run1 발견)", lambda r, l: all(
                    x["date"] != datetime.now().date().isoformat() or x["start_time"] > datetime.now().strftime("%H:%M")
                    for x in r["recommendations"])),
                c("재계획은 LLM 추가 호출 없음 (3회)", lambda r, l: r["llm_calls"] == 3)]},
    {"id": "V3", "kind": "상한에 도달하는 요청", "app": "main", "session": "v-limit",
     "message": "다음 주 수요일 오전 9시 이후에 시작해서 오전 11시 전에 끝나는 대학로 연극 있어?",
     "expected": "평일 오전 공연은 거의 없음 → 후보 확장 → 장르 해제 → 지역 확대 3회 후 멈추고 사유·조정 제안과 함께 응답.",
     "checks": [c("status limit_reached", lambda r, l: r["status"] == "limit_reached"),
                c("재계획 정확히 3회", lambda r, l: r["replan_count"] == 3),
                c("replan 이벤트 3개", lambda r, l: sum(e["type"] == "replan" for e in l) == 3),
                c("상한 안내 포함", lambda r, l: any(n["type"] == "limit" for n in r["notices"]))]},
    {"id": "V4", "kind": "Tool 하나가 실패하는 요청", "app": "bad_kakao", "session": "v-toolfail", "message": S1_MSG,
     "expected": "카카오 키를 무효로 설정 → 주변 장소 Tool 이 AUTH_FAILED. 서비스는 멈추지 않고 공연 추천은 그대로, 상태 partial 과 실패 안내.",
     "checks": [c("status partial", lambda r, l: r["status"] == "partial"),
                c("추천은 유지", lambda r, l: len(r["recommendations"]) >= 1),
                c("실패 기록: search_nearby_places AUTH_FAILED", lambda r, l: any(f["tool"] == NEARBY and f["code"] == "AUTH_FAILED" for f in r["tool_failures"])),
                c("실패 안내 포함", lambda r, l: any(n["type"] == "partial" for n in r["notices"])),
                c("안내가 '주변 장소 실패'를 정확히 말함 (run1 발견)", lambda r, l: any(
                    "주변 장소" in n["message"] and "제외" not in n["message"] for n in r["notices"])),
                c("추천마다 places_status=failed", lambda r, l: all(x["places_status"] == "failed" for x in r["recommendations"]))]},
    {"id": "V5", "kind": "Tool 이 필요 없는 요청", "app": "main", "session": "v-chat", "message": "안녕! 너는 뭘 할 수 있어?",
     "expected": "chitchat 분류 → 계획 단계 생략, Tool 0회, LLM 2회(분석·대화).",
     "checks": [c("status chat", lambda r, l: r["status"] == "chat"),
                c("Tool 호출 0회", lambda r, l: tools_called(l) == []),
                c("plan 노드 미진입", lambda r, l: not any(e["type"] == "node.enter" and e["node"] == "plan" for e in l)),
                c("LLM 2회", lambda r, l: r["llm_calls"] == 2)]},
    {"id": "V6", "kind": "조건이 모자라 되묻는 요청", "app": "main", "session": "v-clarify", "message": "7시 전에 끝나야 해",
     "expected": "계산할 시작점(날짜·시작 시각)이 없음 → Tool 호출 전에 되묻기, LLM 1회.",
     "checks": [c("status clarify", lambda r, l: r["status"] == "clarify"),
                c("날짜·시작 시각을 물음", lambda r, l: {"date", "earliest_start"} <= set(r["missing"])),
                c("Tool 호출 0회", lambda r, l: tools_called(l) == []),
                c("LLM 1회", lambda r, l: r["llm_calls"] == 1),
                c("되묻기 문장에 어색한 조사 없음 (run1 발견)", lambda r, l: "을(를)" not in r["reply"])]},
    {"id": "V7", "kind": "대화 맥락 유지 (V1 후속)", "app": "main", "session": "v-main", "message": "같은 날 뮤지컬로 바꿔줘",
     "expected": "장르만 user 로 갱신, 날짜·시각·예산은 memory 로 유지.",
     "checks": [c("장르=뮤지컬(user)", lambda r, l: r["conditions"]["genre"] == {"value": "뮤지컬", "source": "user"}),
                c("날짜 유지(memory)", lambda r, l: r["conditions"]["date"]["source"] == "memory"),
                c("종료 제한 유지 18:00", lambda r, l: r["conditions"]["end_by"]["value"] == "18:00"),
                c("예산 유지 50000", lambda r, l: r["conditions"]["budget_max"]["value"] == 50000)]},
    {"id": "V8", "kind": "계획 확정 저장 (V7 후속)", "app": "main", "session": "v-main", "message": "1번으로 저장해줘",
     "expected": "직전 추천 1번을 저장소에 저장, Tool 호출 없음.",
     "checks": [c("status saved", lambda r, l: r["status"] == "saved"),
                c("저장된 계획에 날짜·시각", lambda r, l: r["saved_plan"]["date"] and r["saved_plan"]["start_time"]),
                c("Tool 호출 0회", lambda r, l: tools_called(l) == [])]},
    {"id": "V9", "kind": "API 키 누락", "app": "no_kopis", "session": "v-nokey", "message": S1_MSG,
     "expected": "KOPIS 키 없음 → 재계획 없이 즉시 config_missing, 키 이름만 안내(값 노출 없음).",
     "checks": [c("status config_missing", lambda r, l: r["status"] == "config_missing"),
                c("재계획 0회", lambda r, l: r["replan_count"] == 0),
                c("KOPIS_API_KEY 안내", lambda r, l: "KOPIS_API_KEY" in r["reply"])]},
]


def summarize_log(log: list[dict]) -> dict[str, Any]:
    steps = [e["node"] for e in log if e["type"] == "node.enter"]
    tools = [{"tool": e["payload"]["tool"], "ok": e["payload"]["ok"], "error_code": e["payload"].get("error_code"),
              "ms": e["payload"].get("duration_ms"), "cached": e["payload"].get("cached"), "summary": e["payload"].get("summary")}
             for e in log if e["type"] == "tool.response"]
    replans = [e["payload"] for e in log if e["type"] == "replan"]
    decisions = [{"node": e["node"], "decision": e["payload"].get("decision"), "reason": e["payload"].get("reason")}
                 for e in log if e["type"] == "llm.decision"]
    end = next((e["payload"] for e in log if e["type"] == "run.end"), {})
    return {"steps": steps, "tools": tools, "replans": replans, "decisions": decisions, "duration_ms": end.get("duration_ms")}


def write_static_evidence(client: TestClient) -> None:
    (OUT / "tools.json").write_text(json.dumps(client.get("/api/tools").json(), ensure_ascii=False, indent=1), encoding="utf-8")
    mermaid = build_graph().get_graph().draw_mermaid()
    (OUT / "graph.md").write_text("# LangGraph 구조 (명세 4.2)\n\n`build_graph().get_graph().draw_mermaid()` 출력\n\n```mermaid\n"
                                  + mermaid + "\n```\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for f in DATA.glob("*.db*"):
        f.unlink()

    base = Settings.from_env()
    if not (base.llm_api_key and base.kopis_api_key and base.kakao_api_key):
        sys.exit("키 3종이 .env 에 있어야 합니다")
    apps = {"main": create_app(settings=base, db_path=DATA / "main.db"),
            "bad_kakao": create_app(settings=replace(base, kakao_api_key="INVALID-KEY-FOR-VERIFICATION"), db_path=DATA / "bad_kakao.db"),
            "no_kopis": create_app(settings=replace(base, kopis_api_key=None), db_path=DATA / "no_kopis.db")}
    clients = {k: TestClient(a) for k, a in apps.items()}
    write_static_evidence(clients["main"])

    results = []
    for sc in SCENARIOS:
        client = clients[sc["app"]]
        t0 = time.perf_counter()
        res = client.post("/api/chat", json={"session_id": sc["session"], "message": sc["message"]}).json()
        wall = round(time.perf_counter() - t0, 1)
        log = client.get(f"/api/logs/{sc['session']}", params={"run_id": res["run_id"]}).json()["events"]
        (OUT / "logs" / f"{sc['id']}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        checks = [{"check": desc, "ok": ok, "note": note} for desc, fn in sc["checks"] for ok, note in [fn(res, log)]]
        result = {"id": sc["id"], "kind": sc["kind"], "message": sc["message"], "expected": sc["expected"],
                  "status": res["status"], "replan_count": res["replan_count"], "llm_calls": res["llm_calls"],
                  "wall_s": wall, "reply": res["reply"], "conditions": {k: v for k, v in (res.get("conditions") or {}).items() if v},
                  "recommendations": [{k: r.get(k) for k in ("title", "date", "start_time", "end_time", "runtime_min",
                                                             "min_price", "venue_name", "criteria", "places_status")}
                                      | {"places": [p["name"] for p in r.get("places", [])[:3]]}
                                      for r in res["recommendations"]],
                  "excluded_count": len(res["excluded"]), "unjudgeable_count": len(res["unjudgeable"]),
                  "notices": res["notices"], "tool_failures": res["tool_failures"], "relaxed": res["relaxed"],
                  "log": summarize_log(log), "event_count": len(log), "checks": checks,
                  "passed": all(x["ok"] for x in checks)}
        results.append(result)
        mark = "PASS" if result["passed"] else "DIFF"
        print(f"[{mark}] {sc['id']} {sc['kind']}: status={res['status']} replan={res['replan_count']} "
              f"llm={res['llm_calls']} {wall}s  failed={[x['check'] for x in checks if not x['ok']]}")

    (OUT / "scenarios.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                                                    "model": base.llm_model, "results": results},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(results, base.llm_model)
    for client in clients.values():
        client.close()
    for app in apps.values():
        app.state.plans.db.close()


def write_report(results: list[dict], model: str) -> None:
    lines = [f"# 대표 시나리오 검증 기록 (명세 4.7)\n",
             f"- 생성: {datetime.now().isoformat(timespec='seconds')} · 모델 `{model}` · 실제 KOPIS·카카오 API · FastAPI 앱 전체(로깅 Agent 포함)",
             "- 실행: `.venv/Scripts/python scripts/verification/run_scenarios.py` · 원본: `scenarios.json`, `logs/<ID>.json`\n",
             "| ID | 유형 | 상태 | 재계획 | LLM | 시간 | 기대 일치 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['kind']} | `{r['status']}` | {r['replan_count']} | {r['llm_calls']} | {r['wall_s']}초 | "
                     f"{'✅' if r['passed'] else '⚠️ 차이'} |")
    for r in results:
        lg = r["log"]
        lines += [f"\n## {r['id']}. {r['kind']}\n", f"- **요청**: {r['message']}", f"- **기대 동작**: {r['expected']}",
                  f"- **결과**: `{r['status']}` · 재계획 {r['replan_count']}회 · LLM {r['llm_calls']}회 · {r['wall_s']}초 · 이벤트 {r['event_count']}개",
                  f"- **추출 조건**: " + ", ".join(f"{k}={v['value']}({v['source']})" for k, v in r["conditions"].items()),
                  f"- **실행 단계**: {' → '.join(lg['steps'])}"]
        for d in lg["decisions"]:
            lines.append(f"- **LLM 판단** ({d['node']}): {d['decision']} — {d['reason']}")
        for rp in lg["replans"]:
            lines.append(f"- **재계획 #{rp['count']}**: {rp['strategy']} ({rp['reason']})")
        if lg["tools"]:
            lines += ["", "| # | Tool | 결과 | 소요 | 요약 |", "|---|---|---|---|---|"]
            for i, t in enumerate(lg["tools"], 1):
                res = "캐시" if t["cached"] else ("성공" if t["ok"] else t["error_code"])
                lines.append(f"| {i} | {t['tool']} | {res} | {t['ms']}ms | {str(t['summary'])[:70]} |")
        if r["recommendations"]:
            lines += ["", "**추천**"]
            for i, x in enumerate(r["recommendations"], 1):
                lines.append(f"{i}. {x['title']} — {x['date']} {x['start_time']}~{x['end_time']} · {x['min_price']}원 · "
                             f"{x['venue_name']} · 주변: {', '.join(x['places']) or '-'}  \n   근거: {x['criteria']}")
        lines.append(f"\n제외 {r['excluded_count']}건 · 판단 불가 {r['unjudgeable_count']}건 · "
                     f"안내 {[n['message'] for n in r['notices']] or '-'} · 실패 {r['tool_failures'] or '-'}")
        lines += ["", "<details><summary>최종 응답</summary>\n", "```text", r["reply"], "```", "</details>", "",
                  "| 기대 항목 | 결과 |", "|---|---|"]
        lines += [f"| {x['check']} | {'✅' if x['ok'] else '❌ ' + x['note']} |" for x in r["checks"]]
    (OUT / "scenario_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
