"""FakeWorld — 가상의 공연 카탈로그로 KOPIS·카카오 응답을 만들어 내는 가짜 외부 세계.

실제 Tool 코드(KopisClient, NearbyPlacesTool)는 그대로 쓰고, HTTP 만 FakeSession 으로 대체한다.
→ 그래프 테스트가 Tool 계약까지 함께 통과해야 한다 (통합에 가까운 L3).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from xml.sax.saxutils import escape

from app.tools.codes import resolve_genre, resolve_region
from app.tools.factory import build_registry
from fakes import FakeResponse, FakeSession

TODAY = date(2026, 11, 22)   # 일요일
SAT, SUN, WED = "2026-11-28", "2026-11-29", "2026-11-25"


@dataclass
class Show:
    pid: str
    title: str
    genre: str = "연극"
    gu: str = "1111"                 # 종로구(대학로)
    venue_id: str = "FC001"
    venue_name: str = "대학로 테스트극장"
    start: str = "2026-11-01"
    end: str = "2026-12-31"
    runtime: str = "1시간 40분"
    schedule: str = "토요일(15:00)"
    price: str = "전석 40,000원"
    age: str = "만 13세 이상"
    state: str = "공연중"


def _ymd(d: str) -> str:
    return d.replace("-", ".")


@dataclass
class FakeWorld:
    shows: list[Show]
    detail_failures: dict[str, FakeResponse | BaseException] = field(default_factory=dict)
    list_failure: FakeResponse | BaseException | None = None
    kakao_status: int = 200
    places: list[dict] = field(default_factory=lambda: [
        {"place_name": "혜화 국밥", "road_address_name": "서울 종로구 대학로 1", "distance": "30",
         "place_url": "http://place.map.kakao.com/1", "phone": "", "category_name": "음식점 > 한식"}])

    def __post_init__(self):
        self.session = FakeSession()
        self.session.add(r"/pblprfr$", self._list)
        self.session.add(r"/pblprfr/[^/]+$", self._detail)
        self.session.add(r"/prfplc/[^/]+$", self._venue)
        self.session.add(r"dapi\.kakao\.com", self._kakao)

    # ---- KOPIS 공연목록
    def _list(self, url, params):
        if self.list_failure is not None:
            if isinstance(self.list_failure, BaseException):
                raise self.list_failure
            return self.list_failure
        d = f"{params['stdate'][:4]}-{params['stdate'][4:6]}-{params['stdate'][6:]}"
        out = []
        for s in self.shows:
            if not (s.start <= d <= s.end):
                continue
            if "shcate" in params and resolve_genre(s.genre) != params["shcate"]:
                continue
            if "signgucodesub" in params and s.gu != params["signgucodesub"]:
                continue
            if "shprfnm" in params and params["shprfnm"] not in s.title:
                continue
            out.append(s)
        out = out[: int(params.get("rows", 20))]
        body = "".join(f"<db><mt20id>{s.pid}</mt20id><prfnm>{escape(s.title)}</prfnm><prfpdfrom>{_ymd(s.start)}</prfpdfrom>"
                       f"<prfpdto>{_ymd(s.end)}</prfpdto><fcltynm>{escape(s.venue_name)}</fcltynm><genrenm>{s.genre}</genrenm>"
                       f"<prfstate>{s.state}</prfstate><area>서울특별시</area></db>" for s in out)
        return FakeResponse(200, f'<?xml version="1.0" encoding="UTF-8"?><dbs>{body}</dbs>')

    # ---- KOPIS 공연상세
    def _detail(self, url, params):
        pid = url.rsplit("/", 1)[1]
        if pid in self.detail_failures:
            f = self.detail_failures[pid]
            if isinstance(f, BaseException):
                raise f
            return f
        s = next((x for x in self.shows if x.pid == pid), None)
        if s is None:
            return FakeResponse(200, "<dbs><db><returncode>04</returncode><errmsg>NODATA ERROR</errmsg></db></dbs>")
        return FakeResponse(200, (
            f"<dbs><db><mt20id>{s.pid}</mt20id><prfnm>{escape(s.title)}</prfnm><prfpdfrom>{_ymd(s.start)}</prfpdfrom>"
            f"<prfpdto>{_ymd(s.end)}</prfpdto><fcltynm>{escape(s.venue_name)}</fcltynm><mt10id>{s.venue_id}</mt10id>"
            f"<prfruntime>{s.runtime}</prfruntime><prfage>{s.age}</prfage><pcseguidance>{s.price}</pcseguidance>"
            f"<dtguidance>{s.schedule}</dtguidance><genrenm>{s.genre}</genrenm><prfstate>{s.state}</prfstate></db></dbs>"))

    def _venue(self, url, params):
        vid = url.rsplit("/", 1)[1]
        s = next((x for x in self.shows if x.venue_id == vid), None)
        if s is None:
            return FakeResponse(200, "<dbs><db><returncode>04</returncode></db></dbs>")
        return FakeResponse(200, f"<dbs><db><fcltynm>{escape(s.venue_name)}</fcltynm><mt10id>{vid}</mt10id>"
                                 f"<adres>서울특별시 종로구 대학로 1</adres><la>37.58</la><lo>127.00</lo></db></dbs>")

    def _kakao(self, url, params):
        if self.kakao_status != 200:
            return FakeResponse(self.kakao_status, '{"errorType":"AccessDeniedError"}',
                                content_type="application/json;charset=UTF-8")
        return FakeResponse(200,json.dumps({"documents": self.places, "meta": {"total_count": len(self.places)}},
                                            ensure_ascii=False), content_type="application/json;charset=UTF-8")

    # ---- helpers
    def registry(self, kopis_key="K", kakao_key="KK"):
        return build_registry(kopis_key=kopis_key, kakao_key=kakao_key, session=self.session,
                              today=lambda: TODAY, sleep=lambda s: None)

    def detail_calls(self, pid: str) -> int:
        return len(self.session.calls_to(rf"/pblprfr/{re.escape(pid)}$"))

    def list_calls(self) -> list[dict]:
        return [c.params for c in self.session.calls_to(r"/pblprfr$")]


# ---------------------------------------------------------------- 시나리오 카탈로그
def s1_world() -> FakeWorld:
    """토 14시 이후 · 18시 전 종료 · 5만원 이하 · 대학로 연극"""
    return FakeWorld([
        Show("PFA1", "추천될 연극", schedule="토요일(15:00,19:00)", runtime="1시간 40분", price="전석 40,000원"),
        Show("PFA2", "늦게 끝나는 연극", schedule="토요일(17:00)", runtime="100분", price="전석 30,000원"),
        Show("PFA3", "러닝타임 없는 연극", schedule="토요일(14:00)", runtime=" ", price="전석 30,000원"),
        Show("PFA4", "회차 미상 연극", schedule="공연 시간 문의", runtime="70분", price="전석 30,000원"),
        Show("PFA5", "비싼 연극", schedule="토요일(14:00)", runtime="90분", price="R석 60,000원"),
        Show("PFA6", "일요일만 하는 연극", schedule="일요일(15:00)", runtime="90분", price="전석 30,000원"),
        Show("PFM9", "뮤지컬은 제외", genre="뮤지컬", schedule="토요일(15:00)", runtime="90분", price="전석 30,000원"),
    ])


def s2_world() -> FakeWorld:
    """일 19시 이후 · 21시 전 종료 · 3만원 이하 · 대학로 뮤지컬 → 뮤지컬 전부 비쌈 → 장르 해제 후 연극 1편"""
    return FakeWorld([
        Show("PFM1", "비싼 뮤지컬1", genre="뮤지컬", schedule="일요일(19:00)", runtime="90분", price="전석 60,000원"),
        Show("PFM2", "비싼 뮤지컬2", genre="뮤지컬", schedule="일요일(19:30)", runtime="100분", price="R석 50,000원"),
        Show("PFB1", "싸고 짧은 연극", schedule="일요일(19:00)", runtime="60분", price="전석 20,000원"),
        Show("PFB2", "낮 공연 연극", schedule="일요일(15:00)", runtime="60분", price="전석 20,000원"),
    ])


def s3_world() -> FakeWorld:
    """수 9시 이후 · 11시 전 종료 · 대학로 연극 → 어디에도 없음 → 상한 도달"""
    return FakeWorld([
        Show("PFC1", "저녁 연극", schedule="수요일(20:00)", runtime="100분"),
        Show("PFC2", "강남 저녁 연극", gu="1168", venue_id="FC002", schedule="수요일(19:30)", runtime="90분"),
        Show("PFC3", "대학로 저녁 뮤지컬", genre="뮤지컬", schedule="수요일(20:00)", runtime="120분"),
    ])
