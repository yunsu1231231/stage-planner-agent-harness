"""L3 — F3012 발행이 구독자에 의존하지 않음, F3013 로깅 Agent (LLM 없음, 실패해도 대화 계속)."""
from __future__ import annotations

from agents.scripts import DETAIL, NEARBY, S1_ANALYZE, SEARCH, plan
from agents.world import TODAY, s1_world
from app.agents.graph import MainAgent
from app.agents.logging_agent import LoggingAgent
from app.events.bus import EventBus
from app.storage.db import Database
from app.storage.logs import LogRepository
from fakes import FakeLLM


def make(tmp_path, world=None, attach=True, repo=None):
    world = world or s1_world()
    bus = EventBus()
    repo = repo or LogRepository(Database(tmp_path / "t.db"))
    if attach:
        LoggingAgent(repo).attach(bus)
    agent = MainAgent(llm=FakeLLM([S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "ok"]), registry=world.registry(),
                      publish=bus.publish, today=lambda: TODAY)
    return agent, bus, repo


def test_bus_delivers_to_all_subscribers_and_isolates_failures():
    bus, got = EventBus(), []
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("bad subscriber")))
    bus.subscribe(got.append)
    bus.publish({"type": "x"})
    assert got == [{"type": "x"}] and bus.failures == 1


def test_logging_agent_stores_every_event_of_a_run_in_order(tmp_path):
    agent, _, repo = make(tmp_path)
    res = agent.run("s1", "토요일 ...")
    stored = repo.get_session("s1")
    assert [e["seq"] for e in stored] == [e["seq"] for e in res["timeline"]]
    types = {e["type"] for e in stored}
    assert {"run.start", "node.enter", "node.exit", "llm.decision", "plan.created", "tool.request",
            "tool.response", "judge.result", "run.end"} <= types
    analyze_exit = next(e for e in stored if e["type"] == "node.exit" and e["node"] == "analyze")
    assert analyze_exit["payload"]["intent"] == "plan_performance" and analyze_exit["payload"]["reason"]   # 판단 + 이유
    resp = next(e for e in stored if e["type"] == "tool.response")
    assert "duration_ms" in resp["payload"]


def test_agent_runs_normally_without_logging_agent(tmp_path):
    agent, _, repo = make(tmp_path, attach=False)
    assert agent.run("s1", "...")["status"] == "ok" and repo.list_sessions() == []


def test_storage_failure_does_not_break_conversation(tmp_path):
    class BrokenRepo:
        def append(self, event):
            raise OSError("disk full")
    agent, bus, _ = make(tmp_path, repo=BrokenRepo())
    res = agent.run("s1", "...")
    assert res["status"] == "ok"
    assert bus.failures == 0          # 로깅 Agent 가 스스로 삼킨다 (버스까지 올라오지 않음)
