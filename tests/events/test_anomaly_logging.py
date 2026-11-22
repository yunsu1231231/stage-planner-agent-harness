"""L3 — F3020 로깅 Agent: run.end 에 판정 저장, 이상 실행만 진단(LLM), 진단은 판정과 분리, 진단 실패해도 판정 유지."""
from __future__ import annotations

import pytest

from app.agents.logging_agent import LoggingAgent
from app.storage.db import Database
from app.storage.logs import LogRepository


def ev(seq, type_, run="r1", node=None, **payload):
    return {"event_id": f"{run}-{seq}", "session_id": "s1", "run_id": run, "seq": seq,
            "ts": f"2026-11-22T18:00:{seq:02d}.000+09:00", "type": type_, "node": node, "payload": payload}


def run_events(run="r1", repeated=False):
    out = [ev(1, "run.start", run), ev(2, "plan.created", run, "plan", plan_version=0, tasks=[{"tool": "search_performances"}]),
           ev(3, "tool.request", run, "execute", tool="search_performances", args={"date": "2026-11-28"}, cached=False)]
    if repeated:
        out.append(ev(4, "tool.request", run, "execute", tool="search_performances", args={"date": "2026-11-28"}, cached=False))
    out.append(ev(9, "run.end", run, status="ok"))
    return out


class DiagSpy:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, events, report):
        self.calls.append((len(events), [w["rule"] for w in report["warnings"]]))
        if self.fail:
            raise TimeoutError("llm down")
        return "Worker 가 같은 검색을 반복했습니다. 재시도 전 인자 변경 여부를 확인하세요."


@pytest.fixture
def repo(tmp_path):
    return LogRepository(Database(tmp_path / "t.db"))


def feed(agent, events):
    for e in events:
        agent.handle(e)


def test_normal_run_gets_report_and_no_llm_call(repo):
    spy = DiagSpy()
    agent = LoggingAgent(repo, diagnoser=spy, run_async=False)
    feed(agent, run_events())
    [report] = repo.get_reports("s1")
    assert report["verdict"] == "normal" and report["diagnosis"] is None
    assert spy.calls == []                                   # 정상 실행에는 LLM 호출 없음


def test_anomaly_run_is_diagnosed_once_and_stored_separately(repo):
    spy = DiagSpy()
    agent = LoggingAgent(repo, diagnoser=spy, run_async=False)
    feed(agent, run_events(repeated=True))
    [report] = repo.get_reports("s1")
    assert report["verdict"] == "anomaly" and [w["rule"] for w in report["warnings"]] == ["repeated_call"]
    assert spy.calls == [(5, ["repeated_call"])]
    assert report["diagnosis"]["text"].startswith("Worker")
    assert len(report["warnings"]) == 1                      # 진단이 경고 수에 섞이지 않음


def test_diagnosis_failure_keeps_report_and_logs(repo):
    agent = LoggingAgent(repo, diagnoser=DiagSpy(fail=True), run_async=False)
    feed(agent, run_events(repeated=True))
    [report] = repo.get_reports("s1")
    assert report["verdict"] == "anomaly" and report["diagnosis"] is None
    assert len(repo.get_session("s1")) == 5 and agent.diagnosis_failures == 1


def test_inspect_mid_run_returns_interim_report_in_same_format(repo):
    agent = LoggingAgent(repo, run_async=False)
    feed(agent, run_events(repeated=True)[:-1])              # run.end 전
    r = agent.inspect("r1")
    assert r["verdict"] == "anomaly" and r["final"] is False and r["run_id"] == "r1"
    assert agent.inspect("unknown-run")["verdict"] == "undeterminable"


def test_runs_are_judged_independently_and_buffers_released(repo):
    agent = LoggingAgent(repo, run_async=False)
    feed(agent, run_events("r1", repeated=True) + run_events("r2"))
    verdicts = {r["run_id"]: r["verdict"] for r in repo.get_reports("s1")}
    assert verdicts == {"r1": "anomaly", "r2": "normal"}
    assert agent.buffered_runs() == 0


def test_deleting_session_removes_reports_too(repo):
    agent = LoggingAgent(repo, diagnoser=DiagSpy(), run_async=False)
    feed(agent, run_events(repeated=True))
    repo.delete_session("s1")
    assert repo.get_reports("s1") == []
