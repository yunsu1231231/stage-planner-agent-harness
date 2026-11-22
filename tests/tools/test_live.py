"""실제 API 호출 (기본 제외). 실행: .venv/Scripts/python -m pytest -m live tests/tools/test_live.py"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def registry():
    load_dotenv(ROOT / ".env")
    from app.tools.factory import build_registry
    if not (os.getenv("KOPIS_API_KEY") and os.getenv("KAKAO_REST_API_KEY")):
        pytest.skip("키 없음")
    return build_registry(kopis_key=os.getenv("KOPIS_API_KEY"), kakao_key=os.getenv("KAKAO_REST_API_KEY"))


def test_live_chain_search_detail_nearby(registry):
    s = registry.call("search_performances", {"region": "대학로", "genre": "연극"})
    assert s.ok, s.error
    d = registry.call("get_performance_detail", {"performance_id": s.data["items"][0]["performance_id"]})
    assert d.ok or d.error.code in ("NO_RUNTIME",), d.error
    venue_id = d.data["venue_id"] if d.ok else None
    if venue_id:
        n = registry.call("search_nearby_places", {"venue_id": venue_id, "category": "restaurant"})
        assert n.ok or n.error.code == "NO_RESULT", n.error


@pytest.mark.parametrize("region,genre", [("강남", "뮤지컬"), ("홍대", None), ("부산", "연극"), ("서초", "클래식")])
def test_live_region_and_genre_codes_return_matching_area(registry, region, genre):
    r = registry.call("search_performances", {"region": region, "genre": genre, "limit": 5})
    assert r.ok, r.error
    expected_area = "부산광역시" if region == "부산" else "서울특별시"
    assert all(i["area"] == expected_area for i in r.data["items"])
    if genre:
        assert all(genre in i["genre"] for i in r.data["items"])
