"""L1 — F3013 세션 단위 실행 로그 저장, F3014 조회·삭제 (수정 경로 없음)."""
from __future__ import annotations

import pytest

from app.storage.db import Database
from app.storage.logs import LogRepository


@pytest.fixture
def repo(tmp_path):
    return LogRepository(Database(tmp_path / "t.db"))


def ev(session, run, seq, type_, node=None, **payload):
    return {"event_id": f"{session}-{run}-{seq}", "session_id": session, "run_id": run, "seq": seq,
            "ts": f"2026-11-22T18:00:{seq:02d}.000+09:00", "type": type_, "node": node, "payload": payload}


def test_append_keeps_original_event_and_order(repo):
    events = [ev("s1", "r1", 1, "run.start", message="hi"), ev("s1", "r1", 2, "tool.response", "execute",
              tool="search_performances", ok=False, error_code="NO_RESULT"), ev("s1", "r1", 3, "run.end")]
    for e in events:
        repo.append(e)
    got = repo.get_session("s1")
    assert [g["seq"] for g in got] == [1, 2, 3]
    assert got[1]["payload"] == {"tool": "search_performances", "ok": False, "error_code": "NO_RESULT"}  # 가공 없이 원본


def test_sessions_are_isolated_and_summarized(repo):
    for e in [ev("s1", "r1", 1, "run.start"), ev("s1", "r1", 2, "replan", "plan", count=1),
              ev("s1", "r1", 3, "tool.response", "execute", ok=False), ev("s1", "r2", 1, "run.start"),
              ev("s1", "r2", 2, "error", code="LLM_FAILED"), ev("s2", "r3", 1, "run.start")]:
        repo.append(e)
    sessions = {s["session_id"]: s for s in repo.list_sessions()}
    assert set(sessions) == {"s1", "s2"}
    s1 = sessions["s1"]
    assert (s1["run_count"], s1["event_count"], s1["replan_total"], s1["error_count"], s1["tool_failure_count"]) == (2, 5, 1, 1, 1)
    assert [e["session_id"] for e in repo.get_session("s2")] == ["s2"]
    assert [e["run_id"] for e in repo.get_session("s1", run_id="r2")] == ["r2", "r2"]


def test_runs_listed_in_occurrence_order_even_when_seq_restarts(repo):
    for e in [ev("s", "r1", 1, "run.start"), ev("s", "r1", 2, "run.end"), ev("s", "r2", 1, "run.start")]:
        repo.append(e)
    assert [(e["run_id"], e["seq"]) for e in repo.get_session("s")] == [("r1", 1), ("r1", 2), ("r2", 1)]


def test_delete_session(repo):
    repo.append(ev("s1", "r1", 1, "run.start"))
    repo.append(ev("s2", "r2", 1, "run.start"))
    assert repo.delete_session("s1") == 1 and repo.get_session("s1") == [] and repo.get_session("s2")


def test_repository_has_no_update_path():
    assert not any(name.startswith(("update", "edit", "modify", "set_")) for name in dir(LogRepository))
