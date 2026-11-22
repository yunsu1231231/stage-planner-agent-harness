"""L3 — F3021 Planner·Worker 구조 (명세 4.6 F3021 확인 항목). 가짜 LLM + FakeWorld + 실제 Tool + 실제 로깅 Agent."""
from __future__ import annotations

import pytest

from agents.scripts import DETAIL, NEARBY, S1_ANALYZE, SEARCH, analyze, plan
from agents.world import SAT, TODAY, FakeWorld, Show, s1_world
from app.agents.graph import MainAgent
from app.agents.logging_agent import LoggingAgent
from app.agents.worker import TUNABLE, WorkerDecision, classify
from app.events.bus import EventBus
from app.tools.base import ErrorCode, ToolResult
from fakes import FakeLLM


class ListSink:
    def __init__(self):
        self.events = []

    def append(self, e):
        self.events.append(e)


def make_pw(world, *script, worker_llm=True, verifier="logging", registry=None):
    bus, sink = EventBus(), ListSink()
    logging_agent = LoggingAgent(sink, run_async=False)
    logging_agent.attach(bus)
    llm = FakeLLM(list(script))
    agent = MainAgent(llm=llm, registry=registry or world.registry(), publish=bus.publish, today=lambda: TODAY,
                      mode="planner_worker", worker_llm=worker_llm,
                      verifier=logging_agent.inspect if verifier == "logging" else verifier)
    return agent, llm, sink


def of(res, type_):
    return [e for e in res["timeline"] if e["type"] == type_]


def worker_decisions(res):
    return [e["payload"] for e in of(res, "worker.decision")]


# ---------------------------------------------------------------- 구조·형식
def test_pw_graph_adds_verify_between_worker_and_judge():
    agent, _, _ = make_pw(s1_world())
    assert set(agent.graph.get_graph().nodes) - {"__start__", "__end__"} == {
        "analyze", "plan", "execute", "verify", "judge", "respond"}


def test_normal_path_worker_uses_no_llm_and_messages_are_logged():
    agent, llm, sink = make_pw(s1_world(), S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천")
    res = agent.run("s", "...")
    assert res["status"] == "ok" and llm.call_count == 3 and res["worker_llm_calls"] == 0   # 정상 경로 Worker LLM 0회
    msgs = [(e["payload"]["from"], e["payload"]["to"], e["payload"]["kind"]) for e in of(res, "agent.message")]
    assert ("Planner", "Worker", "task_list") in msgs and ("Worker", "Planner", "work_result") in msgs
    assert ("LoggingAgent", "Planner", "verification") in msgs
    task_list = next(e["payload"]["body"] for e in of(res, "agent.message") if e["payload"]["kind"] == "task_list")
    assert {"plan_version", "strategy", "tasks"} <= set(task_list)
    assert {"id", "tool", "args", "fixed_args", "phase"} <= set(task_list["tasks"][0])
    work = next(e["payload"]["body"] for e in of(res, "agent.message") if e["payload"]["kind"] == "work_result")
    assert {"done", "failed", "retried", "unresolved", "replan_requests"} <= set(work)
    assert of(res, "verify.result")[0]["payload"]["verdict"] == "normal"
    assert any(e["type"] == "agent.message" for e in sink.events)                        # 실행 로그에 저장됨


def test_same_recommendations_as_baseline_on_normal_path():
    pw, _, _ = make_pw(s1_world(), S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "x")
    base = MainAgent(llm=FakeLLM([S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "x"]), registry=s1_world().registry(),
                     today=lambda: TODAY)
    key = lambda r: [(x["performance_id"], x["start_time"]) for x in r["recommendations"]]   # noqa: E731
    assert key(pw.run("s", "...")) == key(base.run("s", "..."))


# ---------------------------------------------------------------- Worker LLM: 고칠 수 있는 실패만
def test_no_result_worker_llm_fixes_tunable_arg_and_keeps_fixed_args():
    world = s1_world()
    world.places_min_radius = 1000
    agent, llm, _ = make_pw(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY),
                            {"action": "retry", "reason": "반경 500m 결과 없음 → 1km 로 확대", "radius_m": 1000}, "추천")
    res = agent.run("s", "...")
    calls = [e["payload"]["args"] for e in of(res, "tool.request") if e["payload"]["tool"] == NEARBY]
    assert calls == [{"venue_id": "FC001", "category": "restaurant"},
                     {"venue_id": "FC001", "category": "restaurant", "radius_m": 1000}]   # 같은 Tool, 고정 인자 유지
    assert res["recommendations"][0]["places"] and res["worker_llm_calls"] == 1 and llm.call_count == 4
    [d] = [d for d in worker_decisions(res) if d["llm"]]
    assert d["action"] == "retry" and d["code"] == "NO_RESULT" and d["patch"] == {"radius_m": 1000}


def test_events_are_snapshots_not_live_references():
    """M6 에서 발견: 이벤트가 인자 dict 를 참조로 담아, Worker 재시도로 인자를 고치면 과거 기록까지 바뀌었다."""
    from app.agents.memory import SessionMemory
    from app.agents.runtime import AgentDeps, RunContext
    run = RunContext(deps=AgentDeps(llm=None, registry=None, today=lambda: TODAY), session_id="s", run_id="r",
                     memory=SessionMemory())
    args = {"venue_id": "FC1"}
    e = run.emit("tool.request", "execute", tool=NEARBY, args=args)
    args["radius_m"] = 1000
    assert e["payload"]["args"] == {"venue_id": "FC1"} and run.events[0]["payload"]["args"] == {"venue_id": "FC1"}


def test_worker_llm_off_skips_by_rule():
    world = s1_world()
    world.places_min_radius = 1000
    agent, llm, _ = make_pw(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천", worker_llm=False)
    res = agent.run("s", "...")
    assert llm.call_count == 3 and res["worker_llm_calls"] == 0
    assert res["recommendations"][0]["places_status"] == "none"
    assert [d["reason"] for d in worker_decisions(res)] == ["worker_llm_off"]


def test_fact_query_typo_is_fixed_by_worker_retry():
    world = s1_world()
    agent, _, _ = make_pw(world, analyze("fact_query", keyword="추천될연극"), plan(SEARCH, DETAIL),
                          {"action": "retry", "reason": "띄어쓰기 차이로 결과 없음 → 앞부분만 검색", "keyword": "추천될"}, "100분")
    res = agent.run("s", "추천될연극 러닝타임?")
    assert [p["shprfnm"] for p in world.list_calls()] == ["추천될연극", "추천될"]
    assert res["status"] == "ok" and res["facts"]["title"] == "추천될 연극"


def test_decision_schema_cannot_express_fixed_args():
    """고정 인자(날짜·지역·장르·공연 ID·공연장·장소 종류)는 결정 형식에 아예 없다."""
    fields = set(WorkerDecision.model_fields)
    assert not fields & {"date", "region", "genre", "performance_id", "venue_id", "category"}
    assert TUNABLE[DETAIL] == set()


@pytest.mark.parametrize("decision,why", [
    ({"action": "retry", "reason": "그대로 다시"}, "identical"),
    ({"action": "retry", "reason": "검색어 변경", "keyword": "x"}, "not_tunable"),
])
def test_invalid_retry_decisions_are_rejected_and_skipped(decision, why):
    world = s1_world()
    world.places_min_radius = 1000
    agent, _, _ = make_pw(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), decision, "추천")
    res = agent.run("s", "...")
    nearby_calls = [e for e in of(res, "tool.request") if e["payload"]["tool"] == NEARBY]
    assert len(nearby_calls) == 1                                     # 재호출 없음
    rejected = [d for d in worker_decisions(res) if d.get("rejected")]
    assert rejected and rejected[0]["rejected"] == why and rejected[0]["action"] == "skip"


def test_retry_is_capped_at_two_per_task():
    world = s1_world()
    world.places_min_radius = 99999
    agent, _, _ = make_pw(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY),
                          {"action": "retry", "reason": "1", "radius_m": 1000},
                          {"action": "retry", "reason": "2", "radius_m": 2000}, "추천")
    res = agent.run("s", "...")
    assert len([e for e in of(res, "tool.request") if e["payload"]["tool"] == NEARBY]) == 3   # 원래 1 + 재시도 2
    assert res["worker_llm_calls"] == 2 and worker_decisions(res)[-1]["reason"] == "retry_limit"


# ---------------------------------------------------------------- 규칙으로 판단 → LLM 안 부름
def test_fatal_failure_never_reaches_worker_llm():
    world = s1_world()
    agent, llm, _ = make_pw(world, S1_ANALYZE, plan(SEARCH, DETAIL), registry=world.registry(kopis_key=None))
    res = agent.run("s", "...")
    assert res["status"] == "config_missing" and res["worker_llm_calls"] == 0 and llm.call_count == 2
    assert worker_decisions(res)[0]["action"] == "fatal" and worker_decisions(res)[0]["llm"] is False


def test_classify_rules():
    fail = lambda code, detail=None: ToolResult.failure(code, "x", detail=detail)   # noqa: E731
    assert classify(DETAIL, {}, [], fail(ErrorCode.INVALID_INPUT, "missing:performance_id"))[0] == "missing_arg"
    assert classify(SEARCH, {}, [], fail(ErrorCode.AUTH_FAILED))[0] == "fatal"
    assert classify(SEARCH, {}, [], fail(ErrorCode.UPSTREAM_ERROR))[0] == "skip"
    assert classify(DETAIL, {"performance_id": "PF1"}, ["performance_id"], fail(ErrorCode.NOT_FOUND))[0] == "skip"
    assert classify(SEARCH, {"date": "d"}, ["date"], fail(ErrorCode.NO_RESULT))[0] == "escalate"
    assert classify(SEARCH, {"keyword": "k"}, ["date"], fail(ErrorCode.NO_RESULT)) == ("ask_llm", ["keyword"])
    assert classify(NEARBY, {}, ["venue_id", "category"], fail(ErrorCode.NO_RESULT)) == ("ask_llm", ["radius_m", "size"])


def test_registry_marks_missing_required_argument():
    r = s1_world().registry().call(DETAIL, {})
    assert r.error.code == ErrorCode.INVALID_INPUT and r.error.detail.startswith("missing:")


# ---------------------------------------------------------------- Planner 가 Worker 요청·검증 결과를 반영
def test_worker_replan_request_is_reflected_by_planner():
    world = FakeWorld([Show("PFB1", "싼 연극", schedule="토요일(19:00)", runtime="60분", price="전석 20,000원")])
    agent, llm, _ = make_pw(world, analyze("plan_performance", date=SAT, earliest_start="18:00", end_by="21:00",
                                           region="대학로", genre="뮤지컬"), plan(SEARCH, DETAIL), "추천")
    res = agent.run("s", "...")
    escal = [d for d in worker_decisions(res) if d["action"] == "replan_request"]
    assert escal and escal[0]["llm"] is False                         # 고칠 인자 없음 → 규칙으로 요청
    [rp] = [e["payload"] for e in of(res, "replan")]
    assert rp["strategy"] == "drop_genre"                             # 후보 0건이라 expand_pool 건너뜀
    assert "Worker" in rp["reason"] and "NO_RESULT" in rp["reason"]
    assert res["status"] == "ok" and res["recommendations"][0]["performance_id"] == "PFB1"


def test_planner_rebuilds_task_list_when_verifier_flags_anomaly():
    calls = []

    def verifier(run_id):
        calls.append(run_id)
        if len(calls) == 1:
            return {"run_id": run_id, "verdict": "anomaly", "final": False, "checked": {},
                    "warnings": [{"rule": "repeated_call", "detail": "테스트 주입", "evidence_seqs": [1]}]}
        return {"run_id": run_id, "verdict": "normal", "final": False, "checked": {}, "warnings": []}

    agent, _, _ = make_pw(s1_world(), S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천", verifier=verifier)
    res = agent.run("s", "...")
    rebuilt = [e["payload"] for e in of(res, "plan.created") if e["payload"]["strategy"] == "verified_rebuild"]
    assert len(rebuilt) == 1 and "repeated_call" in rebuilt[0]["reason"]
    assert res["status"] == "ok" and res["verification"]["verdict"] == "anomaly"
