"""L1 — F3008 제약 적합성 판단 (계산식, 역산 기준, 판단 불가). LLM 없음."""
from __future__ import annotations

import pytest

from app.agents.judge import evaluate, parse_age, suggest_adjustments


def detail(**over):
    d = {"performance_id": "PF1", "title": "T", "venue_id": "FC1", "venue_name": "V",
         "start_date": "2026-11-01", "end_date": "2026-12-31", "runtime_min": 100, "runtime_raw": "100분",
         "schedule": {"토요일": ["15:00", "19:00"]}, "schedule_raw": "토요일(15:00,19:00)",
         "min_price": 40000, "price_raw": "전석 40,000원", "age_limit": "만 13세 이상", "genre": "연극"}
    d.update(over)
    return {"ok": True, "data": d, "error": None, "meta": {}}


COND = {"date": "2026-11-28", "earliest_start": "14:00", "end_by": "18:00", "budget_max": 50000}


def test_eligible_uses_formula_start_plus_runtime():
    e = evaluate("PF1", detail(), COND)
    assert e["result"] == "eligible"
    assert (e["start_time"], e["end_time"]) == ("15:00", "16:40")
    assert "15:00" in e["criteria"] and "100분" in e["criteria"] and "16:40" in e["criteria"] and "18:00" in e["criteria"]
    assert e["evidence"] == ["get_performance_detail(PF1)"]


def test_excluded_when_end_exceeds_limit_with_reason():
    e = evaluate("PF1", detail(schedule={"토요일": ["17:00"]}), COND)
    assert e["result"] == "excluded" and e["reason_code"] == "TIME_MISMATCH"
    assert "18:40" in e["reason"] and "18:00" in e["reason"]


def test_start_before_earliest_is_excluded():
    e = evaluate("PF1", detail(schedule={"토요일": ["11:00"]}, runtime_min=60), COND)
    assert e["result"] == "excluded" and "14:00" in e["reason"]


@pytest.mark.parametrize("over,code", [
    ({"min_price": 60000}, "OVER_BUDGET"),
    ({"schedule": {"일요일": ["15:00"]}}, "NO_SHOW_ON_DAY"),
    ({"end_date": "2026-11-27"}, "NOT_ON_DATE"),
])
def test_exclusion_codes(over, code):
    assert evaluate("PF1", detail(**over), COND)["reason_code"] == code


def test_age_limit_excludes_when_child_too_young():
    e = evaluate("PF1", detail(age_limit="만 13세 이상"), {**COND, "age": 8})
    assert e["reason_code"] == "AGE_LIMIT"


def test_no_runtime_is_unjudgeable_not_invented():
    r = {"ok": False, "data": None, "meta": {},
         "error": {"code": "NO_RUNTIME", "message": "x", "retryable": False, "partial": {"title": "무제"}}}
    e = evaluate("PF1", r, COND)
    assert e["result"] == "unjudgeable" and e["reason_code"] == "NO_RUNTIME" and e["title"] == "무제"
    assert "start_time" not in e


def test_unknown_schedule_gives_back_calculated_latest_start():
    e = evaluate("PF1", detail(schedule=None, runtime_min=70), COND)
    assert e["result"] == "unjudgeable" and e["reason_code"] == "NO_SCHEDULE"
    assert e["latest_start"] == "16:50" and "16:50" in e["reason"]   # 18:00 - 70분, 시작 시각은 지어내지 않음


def test_unknown_price_with_budget_is_unjudgeable():
    e = evaluate("PF1", detail(min_price=None), COND)
    assert e["result"] == "unjudgeable" and e["reason_code"] == "NO_PRICE"


def test_no_constraints_means_first_show_of_day():
    e = evaluate("PF1", detail(), {"date": "2026-11-28"})
    assert e["result"] == "eligible" and e["start_time"] == "15:00"


@pytest.mark.parametrize("raw,age", [("만 13세 이상", 13), ("8세 이상", 8), ("전체관람가", 0), ("36개월 이상", 3), ("", None)])
def test_parse_age(raw, age):
    assert parse_age(raw) == age


def test_suggestions_point_to_nearest_relaxation():
    details = [detail(schedule={"토요일": ["17:00"]})["data"], detail(performance_id="PF2", title="비싼", min_price=70000)["data"]]
    tips = suggest_adjustments(details, COND)
    assert any("18:40" in t for t in tips)            # 종료 제한을 늦추면
    assert any("70,000" in t for t in tips)           # 예산을 올리면
