"""L1 — KOPIS 텍스트 파서 (docs/02 6.1, 5.1). 실제 녹화 73건 + 경계값."""
from __future__ import annotations

import pytest

from app.tools.parsers import parse_kopis_date, parse_price, parse_runtime, parse_schedule


@pytest.mark.parametrize("raw,expected", [
    ("1시간 10분", 70), ("100분", 100), ("2시간", 120), ("1시간 30분 (인터미션 15분 포함)", 90),
    ("", None), ("미정", None), ("  ", None),
])
def test_parse_runtime(raw, expected):
    assert parse_runtime(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("전석 30,000원", 30000),
    ("R석 77,000원, S석 55,000원, 시야제한석 20,000원", 20000),
    ("회차별 L  35,000원, 회차별 G  50,000원, 패키지  220,000원", 35000),
    ("무료", 0), ("전석무료", 0), ("", None), ("가격 문의", None),
])
def test_parse_price_uses_minimum(raw, expected):
    assert parse_price(raw) == expected


def test_parse_schedule_range_and_single_days():
    assert parse_schedule("토요일 ~ 일요일(15:00)") == {"토요일": ["15:00"], "일요일": ["15:00"]}
    got = parse_schedule("화요일(20:00), 수요일(16:00,20:00), 목요일 ~ 금요일(20:00), HOL(14:00,18:00)")
    assert got["수요일"] == ["16:00", "20:00"] and got["금요일"] == ["20:00"] and got["HOL"] == ["14:00", "18:00"]
    assert "월요일" not in got


def test_parse_schedule_wraps_week_and_keeps_midnight():
    got = parse_schedule("금요일 ~ 월요일(19:00), 토요일(00:00,19:30)")
    assert set(got) == {"금요일", "토요일", "일요일", "월요일"}
    assert got["토요일"] == ["00:00", "19:00", "19:30"]          # 정렬·중복 제거


@pytest.mark.parametrize("raw", ["", "공연 시간 문의", "추후 공지(미정)"])
def test_parse_schedule_unparseable_returns_none(raw):
    assert parse_schedule(raw) is None


def test_parsers_handle_all_recorded_details(fixture_json):
    pool = [d for d in fixture_json("kopis_detail_pool.json").values() if not d.get("error")]
    assert len(pool) == 73
    for d in pool:
        assert parse_runtime(d["prfruntime"]) is not None, d["prfruntime"]
        assert parse_price(d["pcseguidance"]) is not None, d["pcseguidance"]
        assert parse_schedule(d["dtguidance"]) is not None, d["dtguidance"]


def test_parse_kopis_date():
    assert parse_kopis_date("2026.11.21") == "2026-11-21"
    assert parse_kopis_date("") is None
