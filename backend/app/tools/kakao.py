"""카카오 로컬 외부 API 툴 — F3004 보조 정보 (공연장 주변 식당·카페·주차장).

호출 규약 (docs/02 6.2): Authorization: KakaoAK {key}, HTTP 상태 코드로 실패 구분.
쿼터: 카테고리 검색 일 100,000건 (docs/03 T4).
"""
from __future__ import annotations

import requests

from .base import ErrorCode, ToolResult, never_raises
from .kopis import KopisClient
from .schemas import NearbyInput

CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
CATEGORY_CODES = {"restaurant": "FD6", "cafe": "CE7", "parking": "PK6"}


class KakaoLocalClient:
    def __init__(self, api_key: str | None, session: requests.Session | None = None, timeout: float = 10):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    @never_raises
    def search_category(self, x: str, y: str, category: str, radius_m: int, size: int) -> ToolResult:
        if not self.api_key:
            return ToolResult.failure(ErrorCode.MISSING_API_KEY, "카카오 API 키가 설정되지 않았습니다.")
        try:
            r = self.session.get(CATEGORY_URL, params={"category_group_code": CATEGORY_CODES[category], "x": x, "y": y,
                                                       "radius": radius_m, "sort": "distance", "size": size},
                                 headers={"Authorization": f"KakaoAK {self.api_key}"}, timeout=self.timeout)
        except requests.Timeout:
            return ToolResult.failure(ErrorCode.TIMEOUT, "장소 검색 응답이 늦습니다.", detail="Timeout")
        except requests.RequestException as e:
            return ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "장소 검색 서비스에 연결하지 못했습니다.",
                                      detail=type(e).__name__)
        if r.status_code in (401, 403):
            return ToolResult.failure(ErrorCode.AUTH_FAILED, "카카오 API 키가 유효하지 않습니다.")
        if r.status_code == 400:
            return ToolResult.failure(ErrorCode.INVALID_INPUT, "장소 검색 조건이 올바르지 않습니다.")
        if r.status_code == 429:
            return ToolResult.failure(ErrorCode.RATE_LIMITED, "장소 검색 호출 한도를 넘었습니다.")
        if r.status_code >= 400:
            return ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "장소 검색 서비스 오류입니다.",
                                      detail=f"HTTP {r.status_code}")
        docs = r.json().get("documents") or []
        if not docs:
            return ToolResult.failure(ErrorCode.NO_RESULT, "주변에서 장소를 찾지 못했습니다.", source="KAKAO")
        places = [{"name": d["place_name"], "address": d.get("road_address_name") or d.get("address_name"),
                   "distance_m": int(d["distance"]) if d.get("distance") else None, "url": d["place_url"],
                   "phone": d.get("phone") or None, "category": d.get("category_name")} for d in docs]
        return ToolResult.success({"places": places}, source="KAKAO")


class NearbyPlacesTool:
    """search_nearby_places: venue_id(KOPIS) → 좌표 → 카카오, 또는 좌표 → 카카오."""

    def __init__(self, kopis: KopisClient, kakao: KakaoLocalClient):
        self.kopis, self.kakao = kopis, kakao

    @never_raises
    def search_nearby_places(self, inp: NearbyInput) -> ToolResult:
        if not self.kakao.api_key:
            return ToolResult.failure(ErrorCode.MISSING_API_KEY, "카카오 API 키가 설정되지 않았습니다.")
        if inp.venue_id:
            venue = self.kopis.get_venue(inp.venue_id)
            if not venue.ok:
                return venue
            basis = venue.data
        else:
            basis = {"x": inp.x, "y": inp.y}
        found = self.kakao.search_category(basis["x"], basis["y"], inp.category, inp.radius_m, inp.size)
        if not found.ok:
            return found
        return ToolResult.success({"basis": basis, "category": inp.category, "places": found.data["places"]},
                                  source="KAKAO" if not inp.venue_id else "KOPIS+KAKAO")
