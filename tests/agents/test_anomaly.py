"""L1 — F3020 이상 징후 규칙 판정 (LLM 없음). 명세 4.6: 반복 호출·과도한 재계획·계획 외 호출, 근거 없으면 '판정 불가'."""
from __future__ import annotations

from app.agents.anomaly import evaluate_run

S, D, N = "search_performances", "get_performance_detail", "search_nearby_places"


def ev(seq, type_, node=None, **payload):
    return {"seq": seq, "run_id": "r1", "session_id": "s", "type": type_, "node": node, "payload": payload}


def plan(seq, *tools, version=0):
    return ev(seq, "plan.created", "plan", plan_version=version, strategy="initial", tasks=[{"tool": t} for t in tools])


def req(seq, tool, cached=False, **args):
    return ev(seq, "tool.request", "execute", tool=tool, args=args, cached=cached)


def normal_run():
    return [ev(1, "run.start"), plan(2, S, D), req(3, S, date="2026-11-28"), req(4, D, performance_id="PF1"),
            req(5, D, performance_id="PF2"), ev(6, "run.end", status="ok")]


def rules(report):
    return {w["rule"] for w in report["warnings"]}


def test_normal_run_has_no_warnings_and_checks_all_rules():
    r = evaluate_run(normal_run())
    assert r["verdict"] == "normal" and r["warnings"] == []
    assert set(r["checked"]) == {"repeated_call", "excessive_replan", "unplanned_call"}
    assert all(v == "ok" for v in r["checked"].values())


def test_repeated_identical_real_calls_are_flagged_but_cache_hits_are_not():
    events = normal_run()[:-1] + [req(7, D, performance_id="PF1"), req(8, D, cached=True, performance_id="PF2"),
                                  ev(9, "run.end")]
    r = evaluate_run(events)
    assert r["verdict"] == "anomaly" and rules(r) == {"repeated_call"}
    w = r["warnings"][0]
    assert w["evidence_seqs"] == [4, 7] and "PF1" in w["detail"]


def test_replan_reaching_limit_is_excessive():
    events = [ev(1, "run.start"), plan(2, S, D)] + [ev(3 + i, "replan", "plan", count=i + 1, strategy="x") for i in range(3)] \
        + [ev(9, "run.end")]
    r = evaluate_run(events, replan_limit=3)
    assert rules(r) == {"excessive_replan"} and r["warnings"][0]["evidence_seqs"] == [3, 4, 5]
    assert evaluate_run(events[:3] + events[-1:], replan_limit=3)["verdict"] == "normal"   # 1회는 정상


def test_tool_not_in_active_plan_is_unplanned():
    events = [ev(1, "run.start"), plan(2, S, D), req(3, S), req(4, N, venue_id="FC1"), ev(5, "run.end")]
    r = evaluate_run(events)
    assert rules(r) == {"unplanned_call"} and r["warnings"][0]["evidence_seqs"] == [4]


def test_active_plan_is_the_latest_one():
    events = [ev(1, "run.start"), plan(2, S), req(3, S), plan(4, S, D, N, version=1), req(5, N), ev(6, "run.end")]
    assert evaluate_run(events)["verdict"] == "normal"


def test_tool_calls_without_any_plan_are_undeterminable_not_normal():
    events = [ev(1, "run.start"), req(2, S), ev(3, "run.end")]
    r = evaluate_run(events)
    assert r["verdict"] == "undeterminable" and r["checked"]["unplanned_call"] == "undeterminable"


def test_no_evidence_is_undeterminable():
    assert evaluate_run([])["verdict"] == "undeterminable"
    assert evaluate_run(normal_run()[:-1], final=True)["verdict"] == "undeterminable"     # run.end 없음
    assert evaluate_run(normal_run()[:-1], final=False)["verdict"] == "normal"           # 실행 중간 점검


def test_warning_beats_undeterminable():
    events = [ev(1, "run.start"), req(2, S, a=1), req(3, S, a=1), ev(4, "run.end")]
    r = evaluate_run(events)
    assert r["verdict"] == "anomaly" and rules(r) == {"repeated_call"}
