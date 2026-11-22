"""KOPIS(공연예술통합전산망) 외부 API 툴 — F3002 후보 조회, F3003 상세정보, 공연시설 좌표.

호출 규약 (docs/02 6.1, 기획 검증에서 확인):
  - 자체 식별 User-Agent 필수 (기본 UA는 WAF 차단, 브라우저 위장 금지)
  - 세션 재사용, XML 전용, charset 없음 → UTF-8 강제
  - 오류도 HTTP 200 + returncode (02 키 오류, 04 데이터 없음)
  - 간헐적 400 차단·연결 끊김·비 XML 응답 → 최대 3회, 2s/4s 백오프
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Callable

import requests

from .base import ErrorCode, ToolResult, never_raises
from .codes import resolve_genre, resolve_region
from .parsers import parse_kopis_date, parse_price, parse_runtime, parse_schedule
from .schemas import DetailInput, SearchInput

BASE_URL = "https://www.kopis.or.kr/openApi/restful"
USER_AGENT = "ai-planner/0.1 (SSAFY AI core project)"
_NODATA = "NODATA"


def _t(el: ET.Element, tag: str) -> str:
    return (el.findtext(tag) or "").strip()


class KopisClient:
    def __init__(self, api_key: str | None, session: requests.Session | None = None,
                 today: Callable[[], date] | None = None, sleep: Callable[[float], None] = time.sleep,
                 max_attempts: int = 3, timeout: float = 10):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.today = today or date.today
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.timeout = timeout

    # ------------------------------------------------------------ transport
    def _get(self, path: str, params: dict) -> tuple[list[ET.Element] | str | None, ToolResult | None, int]:
        """→ (db 목록 | _NODATA, 실패 결과, 시도 횟수). 실패 결과가 있으면 그것을 그대로 돌려줄 것."""
        last = ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "공연 정보 서비스가 응답하지 않습니다.")
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = self.session.get(f"{BASE_URL}/{path}", params={"service": self.api_key, **params},
                                     headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
            except requests.Timeout:
                last = ToolResult.failure(ErrorCode.TIMEOUT, "공연 정보 서비스 응답이 늦습니다.", detail="Timeout")
            except requests.RequestException as e:
                last = ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "공연 정보 서비스에 연결하지 못했습니다.",
                                          detail=type(e).__name__)
            else:
                r.encoding = "utf-8"
                if r.status_code == 429:
                    return None, ToolResult.failure(ErrorCode.RATE_LIMITED, "공연 정보 호출 한도를 넘었습니다."), attempt
                if r.status_code >= 400:   # 400 Request Blocked(HTML) / 5xx → 재시도
                    last = ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "공연 정보 서비스가 요청을 거절했습니다.",
                                              detail=f"HTTP {r.status_code}")
                else:
                    try:
                        root = ET.fromstring(r.text)
                    except ET.ParseError:
                        last = ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "공연 정보 응답 형식이 올바르지 않습니다.",
                                                  detail="ParseError")
                    else:
                        rc = root.findtext("db/returncode")
                        if rc == "02":
                            return None, ToolResult.failure(ErrorCode.AUTH_FAILED,
                                                            "KOPIS API 키가 유효하지 않습니다."), attempt
                        if rc == "04":
                            return _NODATA, None, attempt
                        if rc:
                            return None, ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "공연 정보 서비스 오류입니다.",
                                                            detail=f"returncode {rc}"), attempt
                        return root.findall("db"), None, attempt
            if attempt < self.max_attempts:
                self.sleep(2 * attempt)
        return None, last, self.max_attempts

    def _missing_key(self) -> ToolResult | None:
        if not self.api_key:
            return ToolResult.failure(ErrorCode.MISSING_API_KEY, "KOPIS API 키가 설정되지 않았습니다.")
        return None

    # ------------------------------------------------------------ F3002
    @never_raises
    def search_performances(self, inp: SearchInput) -> ToolResult:
        if fail := self._missing_key():
            return fail
        params: dict = {"cpage": 1, "rows": inp.limit}
        if inp.region:
            region = resolve_region(inp.region)
            if region is None:
                return ToolResult.failure(ErrorCode.INVALID_INPUT,
                                          f"알 수 없는 지역입니다: {inp.region} (예: 대학로, 강남, 종로구, 서울)")
            params.update(region)
        if inp.genre:
            code = resolve_genre(inp.genre)
            if code is None:
                return ToolResult.failure(ErrorCode.INVALID_INPUT,
                                          f"알 수 없는 장르입니다: {inp.genre} (예: 연극, 뮤지컬, 클래식)")
            params["shcate"] = code

        today = self.today()
        defaults, estimated, note = [], False, None
        if inp.date is None:
            target = today
            defaults.append("date")
        else:
            target = date.fromisoformat(inp.date)
            if target < today:
                estimated = True
                note = f"요청한 날짜 {inp.date}는 지난 날짜라 오늘 {today.isoformat()} 기준으로 조회했습니다."
                target = today
        ymd = target.strftime("%Y%m%d")
        params.update({"stdate": ymd, "eddate": ymd})

        dbs, fail, attempts = self._get("pblprfr", params)
        if fail:
            return fail
        items = [] if dbs == _NODATA else [
            {"performance_id": _t(d, "mt20id"), "title": _t(d, "prfnm"), "venue_name": _t(d, "fcltynm"),
             "start_date": parse_kopis_date(_t(d, "prfpdfrom")), "end_date": parse_kopis_date(_t(d, "prfpdto")),
             "genre": _t(d, "genrenm"), "state": _t(d, "prfstate"), "area": _t(d, "area")}
            for d in dbs if _t(d, "mt20id") and _t(d, "prfstate") != "공연완료"
        ]
        if not items:
            return ToolResult.failure(ErrorCode.NO_RESULT, "조건에 맞는 공연을 찾지 못했습니다.",
                                      source="KOPIS", attempts=attempts)
        query = {"date": target.isoformat(), "region": inp.region, "genre": inp.genre, "limit": inp.limit}
        return ToolResult.success({"query": query, "items": items}, source="KOPIS", defaults=defaults,
                                  estimated=estimated, note=note, attempts=attempts)

    # ------------------------------------------------------------ F3003
    @never_raises
    def get_performance_detail(self, inp: DetailInput) -> ToolResult:
        if fail := self._missing_key():
            return fail
        dbs, fail, attempts = self._get(f"pblprfr/{inp.performance_id}", {})
        if fail:
            return fail
        if dbs == _NODATA or not dbs:
            return ToolResult.failure(ErrorCode.NOT_FOUND, f"공연 정보를 찾지 못했습니다: {inp.performance_id}")
        d = dbs[0]
        title, venue_name = _t(d, "prfnm"), _t(d, "fcltynm")
        runtime_raw, schedule_raw, price_raw = _t(d, "prfruntime"), _t(d, "dtguidance"), _t(d, "pcseguidance")
        runtime = parse_runtime(runtime_raw)
        if runtime is None:
            return ToolResult.failure(
                ErrorCode.NO_RUNTIME, "러닝타임 정보가 없어 시간 조건을 판단할 수 없습니다.",
                partial={"performance_id": inp.performance_id, "title": title, "venue_name": venue_name},
                source="KOPIS")
        schedule, price = parse_schedule(schedule_raw), parse_price(price_raw)
        missing = [name for name, v in (("schedule", schedule), ("price", price)) if v is None]
        return ToolResult.success({
            "performance_id": inp.performance_id, "title": title, "genre": _t(d, "genrenm"), "state": _t(d, "prfstate"),
            "venue_id": _t(d, "mt10id"), "venue_name": venue_name,
            "start_date": parse_kopis_date(_t(d, "prfpdfrom")), "end_date": parse_kopis_date(_t(d, "prfpdto")),
            "runtime_min": runtime, "runtime_raw": runtime_raw,
            "schedule": schedule, "schedule_raw": schedule_raw,
            "min_price": price, "price_raw": price_raw,
            "age_limit": _t(d, "prfage"),
        }, source="KOPIS", missing=missing, attempts=attempts)

    # ------------------------------------------------------------ 공연시설 좌표 (search_nearby_places 내부용)
    @never_raises
    def get_venue(self, venue_id: str) -> ToolResult:
        if fail := self._missing_key():
            return fail
        dbs, fail, _ = self._get(f"prfplc/{venue_id}", {})
        if fail:
            return fail
        if dbs == _NODATA or not dbs:
            return ToolResult.failure(ErrorCode.NOT_FOUND, f"공연장 정보를 찾지 못했습니다: {venue_id}")
        v = dbs[0]
        x, y = _t(v, "lo"), _t(v, "la")
        if not (x and y):
            return ToolResult.failure(ErrorCode.NOT_FOUND, "공연장 좌표 정보가 없습니다.")
        return ToolResult.success({"venue_id": venue_id, "venue_name": _t(v, "fcltynm"),
                                   "address": _t(v, "adres"), "x": x, "y": y}, source="KOPIS")
