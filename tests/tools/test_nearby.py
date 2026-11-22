"""L2 — F3004 보조 정보 검색 (카카오 로컬 + KOPIS 공연시설 좌표)."""
from __future__ import annotations

from app.tools.base import ErrorCode
from tools.conftest import KAKAO_CATEGORY, KAKAO_KEY, KOPIS_VENUE, kakao_json, kopis_xml


def test_nearby_by_coordinates(make_registry, session, fixture_text):
    session.add(KAKAO_CATEGORY, kakao_json(fixture_text("kakao_category_fd6.json")))
    r = make_registry().call("search_nearby_places", {"x": "127.0026", "y": "37.5829", "category": "restaurant"})
    call = session.calls[0]
    assert call.params["category_group_code"] == "FD6" and call.params["radius"] == 500 and call.params["size"] == 5
    assert call.headers["Authorization"] == f"KakaoAK {KAKAO_KEY}"
    p = r.data["places"][0]
    assert (p["name"], p["distance_m"]) == ("거복이식당 대학로", 4)
    assert p["url"].startswith("http://place.map.kakao.com/") and p["address"]
    assert r.data["basis"]["x"] == "127.0026"


def test_nearby_by_venue_id_resolves_coordinates_via_kopis(make_registry, session, fixture_text):
    session.add(KOPIS_VENUE, kopis_xml(fixture_text("kopis_venue.xml")))
    session.add(KAKAO_CATEGORY, kakao_json(fixture_text("kakao_category_fd6.json")))
    r = make_registry().call("search_nearby_places", {"venue_id": "FC001091", "category": "restaurant"})
    assert session.calls[0].url.endswith("/prfplc/FC001091")
    kakao = session.calls_to(KAKAO_CATEGORY)[0]
    assert kakao.params["x"].startswith("127.0026") and kakao.params["y"].startswith("37.5829")
    assert r.data["basis"]["venue_name"] == "대학로 스카이씨어터"
    assert "종로구" in r.data["basis"]["address"]


def test_nearby_category_mapping(make_registry, session, fixture_text):
    session.add(KAKAO_CATEGORY, kakao_json(fixture_text("kakao_category_fd6.json")))
    reg = make_registry()
    reg.call("search_nearby_places", {"x": "1", "y": "2", "category": "cafe"})
    reg.call("search_nearby_places", {"x": "1", "y": "2", "category": "parking"})
    assert [c.params["category_group_code"] for c in session.calls] == ["CE7", "PK6"]


def test_nearby_no_result(make_registry, session, fixture_text):
    session.add(KAKAO_CATEGORY, kakao_json({"documents": [], "meta": {"total_count": 0, "pageable_count": 0, "is_end": True}}))
    r = make_registry().call("search_nearby_places", {"x": "1", "y": "2", "category": "restaurant"})
    assert r.ok is False and r.error.code == ErrorCode.NO_RESULT


def test_nearby_http_errors_map_to_codes(make_registry, session, fixture_text):
    session.add(KAKAO_CATEGORY, kakao_json(fixture_text("kakao_fail_bad_key.json"), 401),
                kakao_json(fixture_text("kakao_fail_bad_input.json"), 400),
                kakao_json({"errorType": "RequestThrottled"}, 429), repeat_last=False)
    reg = make_registry()
    codes = [reg.call("search_nearby_places", {"x": "1", "y": "2", "category": "restaurant"}).error.code
             for _ in range(3)]
    assert codes == [ErrorCode.AUTH_FAILED, ErrorCode.INVALID_INPUT, ErrorCode.RATE_LIMITED]


def test_nearby_unknown_venue_is_not_found(make_registry, session, fixture_text):
    session.add(KOPIS_VENUE, kopis_xml(fixture_text("kopis_fail_bad_id.xml")))
    r = make_registry().call("search_nearby_places", {"venue_id": "FC999", "category": "restaurant"})
    assert r.error.code == ErrorCode.NOT_FOUND and session.calls_to(KAKAO_CATEGORY) == []


def test_nearby_missing_key(make_registry, session):
    r = make_registry(kakao_key=None).call("search_nearby_places", {"x": "1", "y": "2", "category": "restaurant"})
    assert r.error.code == ErrorCode.MISSING_API_KEY and session.calls == []
