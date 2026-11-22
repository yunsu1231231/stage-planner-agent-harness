"""L1/L4 — F3015 계획 저장·조회(겹침 알림), F3016 수정·삭제."""
from __future__ import annotations

import pytest

from app.storage.db import Database
from app.storage.plans import PlanRepository


@pytest.fixture
def repo(tmp_path):
    return PlanRepository(Database(tmp_path / "t.db"))


def p(**over):
    base = {"performance_id": "PF1", "title": "연극A", "venue_name": "극장", "date": "2026-11-28",
            "start_time": "15:00", "end_time": "16:40", "price": 40000, "memo": None, "source_session_id": "s"}
    return {**base, **over}


def test_create_returns_plan_with_core_values_and_timestamps(repo):
    plan, overlaps = repo.create(p())
    assert plan["id"] == 1 and overlaps == []
    assert (plan["title"], plan["date"], plan["start_time"], plan["end_time"]) == ("연극A", "2026-11-28", "15:00", "16:40")
    assert plan["created_at"] and plan["updated_at"] == plan["created_at"]
    assert repo.get(1) == plan


@pytest.mark.parametrize("start,end,overlap", [
    ("16:00", "17:00", True),     # 뒤쪽 걸침
    ("14:00", "15:30", True),     # 앞쪽 걸침
    ("15:30", "16:00", True),     # 포함
    ("16:40", "18:00", False),    # 끝나는 순간 시작 — 겹치지 않음 [start, end)
    ("13:00", "15:00", False),
])
def test_overlap_rule_half_open_interval(repo, start, end, overlap):
    repo.create(p())
    _, overlaps = repo.create(p(title="연극B", start_time=start, end_time=end))
    assert bool(overlaps) is overlap


def test_overlap_saves_anyway_and_ignores_other_dates(repo):
    repo.create(p())
    plan, overlaps = repo.create(p(title="연극B", start_time="16:00", end_time="17:30"))
    assert plan["id"] == 2 and [o["title"] for o in overlaps] == ["연극A"]   # 저장은 막지 않음
    _, other_day = repo.create(p(title="연극C", date="2026-11-29"))
    assert other_day == []


def test_list_sorted_and_filter_by_date(repo):
    repo.create(p(title="늦은", start_time="19:00", end_time="20:00"))
    repo.create(p(title="이른", start_time="11:00", end_time="12:00"))
    repo.create(p(title="다른날", date="2026-11-29"))
    assert [x["title"] for x in repo.list()] == ["이른", "늦은", "다른날"]
    assert [x["title"] for x in repo.list(date="2026-11-29")] == ["다른날"]


def test_update_changes_fields_rechecks_overlap_excluding_self(repo):
    repo.create(p())
    repo.create(p(title="연극B", start_time="18:00", end_time="19:00"))
    plan, overlaps = repo.update(2, {"start_time": "16:00", "end_time": "17:00", "memo": "당겨짐"})
    assert plan["start_time"] == "16:00" and plan["memo"] == "당겨짐"
    assert [o["id"] for o in overlaps] == [1]
    _, self_only = repo.update(1, {"memo": "자기 자신과는 겹침 아님"})
    assert [o["id"] for o in self_only] == [2]
    assert repo.update(99, {"memo": "x"}) is None


def test_delete(repo):
    repo.create(p())
    assert repo.delete(1) is True and repo.get(1) is None and repo.delete(1) is False
