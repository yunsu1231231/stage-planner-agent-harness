"""L2 — F3002 후보 조회 / F3003 상세정보 (KOPIS). 녹화 응답 + 기획 검증에서 발견한 실제 동작."""
from __future__ import annotations

import requests

from app.tools.base import ErrorCode
from app.tools.schemas import DetailInput, SearchInput
from tools.conftest import KOPIS_DETAIL, KOPIS_KEY, KOPIS_LIST, UA, blocked, kopis_xml

LIST_ONE_DONE = """<?xml version="1.0" encoding="UTF-8"?><dbs>
<db><mt20id>PF1</mt20id><prfnm>진행 중</prfnm><prfpdfrom>2026.11.01</prfpdfrom><prfpdto>2026.12.31</prfpdto><fcltynm>A</fcltynm><genrenm>연극</genrenm><prfstate>공연중</prfstate><area>서울특별시</area></db>
<db><mt20id>PF2</mt20id><prfnm>개막 예정</prfnm><prfpdfrom>2026.11.27</prfpdfrom><prfpdto>2026.12.31</prfpdto><fcltynm>B</fcltynm><genrenm>연극</genrenm><prfstate>공연예정</prfstate><area>서울특별시</area></db>
<db><mt20id>PF3</mt20id><prfnm>끝난 공연</prfnm><prfpdfrom>2026.10.01</prfpdfrom><prfpdto>2026.11.20</prfpdto><fcltynm>C</fcltynm><genrenm>연극</genrenm><prfstate>공연완료</prfstate><area>서울특별시</area></db>
</dbs>"""


# ---------------------------------------------------------------- F3002 search_performances
def test_search_defaults_to_today_and_sends_identifying_ua(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_list.xml")))
    r = make_kopis().search_performances(SearchInput())
    call = session.calls[0]
    assert call.params["stdate"] == call.params["eddate"] == "20261122"
    assert call.params["service"] == KOPIS_KEY
    assert call.headers["User-Agent"] == UA
    assert "prfstate" not in call.params                     # 공연예정 누락 방지
    assert r.ok and "date" in r.meta["defaults"] and r.data["query"]["date"] == "2026-11-22"


def test_search_parses_items_with_korean_and_iso_dates(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_list.xml")))
    items = make_kopis().search_performances(SearchInput(date="2026-11-22")).data["items"]
    assert len(items) == 20
    first = items[0]
    assert first["performance_id"] == "PF306989"
    assert first["title"] == "제7회 서울연극25페스티벌, 한남서림"   # utf-8 강제 안 하면 깨진다
    assert first["start_date"] == "2026-11-21" and first["genre"] == "연극"


def test_search_maps_region_and_genre_names_to_codes(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_list.xml")))
    make_kopis().search_performances(SearchInput(date="2026-11-28", region="대학로", genre="연극"))
    p = session.calls[0].params
    assert (p["signgucode"], p["signgucodesub"], p["shcate"]) == ("11", "1111", "AAAA")


def test_search_unknown_region_or_genre_is_invalid_input_without_call(make_kopis, session):
    r1 = make_kopis().search_performances(SearchInput(region="아틀란티스"))
    r2 = make_kopis().search_performances(SearchInput(genre="e스포츠"))
    assert r1.error.code == r2.error.code == ErrorCode.INVALID_INPUT
    assert session.calls == []


def test_search_past_date_is_clamped_and_marked_estimated(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_list.xml")))
    r = make_kopis().search_performances(SearchInput(date="2026-11-01"))
    assert session.calls[0].params["stdate"] == "20261122"
    assert r.meta["estimated"] is True and "2026-11-01" in r.meta["note"] and "2026-11-22" in r.meta["note"]


def test_search_excludes_finished_but_keeps_upcoming(make_kopis, session):
    session.add(KOPIS_LIST, kopis_xml(LIST_ONE_DONE))
    ids = [i["performance_id"] for i in make_kopis().search_performances(SearchInput(date="2026-11-28")).data["items"]]
    assert ids == ["PF1", "PF2"]


def test_search_empty_result_is_no_result(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_fail_no_result.xml")))
    r = make_kopis().search_performances(SearchInput())
    assert r.ok is False and r.error.code == ErrorCode.NO_RESULT and r.error.retryable


def test_search_bad_key_is_auth_failed(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_fail_bad_key.xml")))
    r = make_kopis().search_performances(SearchInput())
    assert r.error.code == ErrorCode.AUTH_FAILED and not r.error.retryable


def test_search_missing_key_fails_fast_without_http(make_kopis, session):
    r = make_kopis(api_key=None).search_performances(SearchInput())
    assert r.error.code == ErrorCode.MISSING_API_KEY and session.calls == []


def test_search_retries_transient_block_then_succeeds(make_kopis, session, fixture_text, sleep_spy):
    session.add(KOPIS_LIST, blocked(), kopis_xml(fixture_text("kopis_list.xml")))
    r = make_kopis().search_performances(SearchInput())
    assert r.ok and len(session.calls) == 2 and sleep_spy.calls == [2]
    assert r.meta["attempts"] == 2


def test_search_gives_up_after_three_attempts(make_kopis, session, sleep_spy):
    session.add(KOPIS_LIST, blocked())
    r = make_kopis().search_performances(SearchInput())
    assert r.error.code == ErrorCode.UPSTREAM_ERROR and len(session.calls) == 3 and sleep_spy.calls == [2, 4]


def test_search_retries_connection_reset_and_non_xml(make_kopis, session, fixture_text):
    session.add(KOPIS_LIST, requests.ConnectionError("reset"), kopis_xml("<html>not xml"),
                kopis_xml(fixture_text("kopis_list.xml")))
    assert make_kopis().search_performances(SearchInput()).ok
    assert len(session.calls) == 3


# ---------------------------------------------------------------- F3003 get_performance_detail
def test_detail_extracts_judgement_attributes(make_kopis, session, fixture_text):
    session.add(KOPIS_DETAIL, kopis_xml(fixture_text("kopis_detail.xml")))
    r = make_kopis().get_performance_detail(DetailInput(performance_id="PF306989"))
    d = r.data
    assert session.calls[0].url.endswith("/pblprfr/PF306989")
    assert (d["runtime_min"], d["min_price"], d["venue_id"]) == (70, 30000, "FC001091")
    assert d["schedule"] == {"토요일": ["15:00"], "일요일": ["15:00"]}
    assert d["age_limit"] == "만 10세 이상" and d["genre"] == "연극"           # 함께 제시할 속성
    assert d["start_date"] == "2026-11-21" and d["runtime_raw"] == "1시간 10분"
    assert r.meta.get("missing", []) == []


def test_detail_unknown_id_is_not_found(make_kopis, session, fixture_text):
    session.add(KOPIS_DETAIL, kopis_xml(fixture_text("kopis_fail_bad_id.xml")))
    r = make_kopis().get_performance_detail(DetailInput(performance_id="PF000000000"))
    assert r.error.code == ErrorCode.NOT_FOUND


def test_detail_blank_runtime_is_no_runtime_and_not_invented(make_kopis, session, fixture_text):
    xml = fixture_text("kopis_detail.xml").replace("<prfruntime>1시간 10분</prfruntime>", "<prfruntime> </prfruntime>")
    session.add(KOPIS_DETAIL, kopis_xml(xml))
    r = make_kopis().get_performance_detail(DetailInput(performance_id="PF306989"))
    assert r.ok is False and r.error.code == ErrorCode.NO_RUNTIME
    assert r.error.partial["title"] == "제7회 서울연극25페스티벌, 한남서림"   # 제외 사유 표시용
    assert "runtime_min" not in r.error.partial


def test_detail_unparseable_schedule_is_null_and_flagged(make_kopis, session, fixture_text):
    xml = fixture_text("kopis_detail.xml").replace("토요일 ~ 일요일(15:00)", "공연 시간 문의")
    session.add(KOPIS_DETAIL, kopis_xml(xml))
    r = make_kopis().get_performance_detail(DetailInput(performance_id="PF306989"))
    assert r.ok and r.data["schedule"] is None and r.meta["missing"] == ["schedule"]
    assert r.data["schedule_raw"] == "공연 시간 문의"


def test_detail_ids_from_search_feed_detail(make_registry, session, fixture_text):
    """F3002→F3003 연결: 후보 Tool의 식별자가 상세 Tool 입력으로 그대로 쓰인다 (명세 4.1)."""
    session.add(KOPIS_LIST, kopis_xml(fixture_text("kopis_list.xml")))
    session.add(KOPIS_DETAIL, kopis_xml(fixture_text("kopis_detail.xml")))
    reg = make_registry()
    pid = reg.call("search_performances", {}).data["items"][0]["performance_id"]
    assert reg.call("get_performance_detail", {"performance_id": pid}).ok
