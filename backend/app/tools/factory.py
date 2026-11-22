"""필수 외부 API 툴 3종을 등록한 레지스트리 생성. 의존성(세션·키·시계)은 주입 가능."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from .kakao import KakaoLocalClient, NearbyPlacesTool
from .kopis import USER_AGENT, KopisClient
from .registry import ToolRegistry, ToolSpec
from .schemas import DetailInput, NearbyInput, SearchInput

KST = ZoneInfo("Asia/Seoul")

DESCRIPTIONS = {
    "search_performances": (
        "사용자가 볼 공연을 아직 정하지 않았을 때, 날짜·지역·장르 조건으로 실제 공연 중인 후보 목록을 찾을 때 사용한다. "
        "결과의 performance_id 를 get_performance_detail 에 넘긴다."),
    "get_performance_detail": (
        "후보 공연의 러닝타임·요일별 회차 시각·가격·관람 연령을 확인해 시간과 예산 조건을 판단해야 할 때 사용한다. "
        "performance_id 는 search_performances 결과에서 얻는다."),
    "search_nearby_places": (
        "추천할 공연장 주변의 식당·카페·주차장을 함께 안내해야 할 때 사용한다. "
        "get_performance_detail 결과의 venue_id 를 넣거나 좌표를 넣는다."),
}


def kst_today() -> date:
    return datetime.now(KST).date()


def build_registry(kopis_key: str | None, kakao_key: str | None, session: requests.Session | None = None,
                   today: Callable[[], date] | None = None,
                   sleep: Callable[[float], None] | None = None) -> ToolRegistry:
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
    kopis = KopisClient(kopis_key, session=session, today=today or kst_today, sleep=sleep or time.sleep)
    nearby = NearbyPlacesTool(kopis, KakaoLocalClient(kakao_key, session=session))

    registry = ToolRegistry()
    registry.register(ToolSpec("search_performances", "external", DESCRIPTIONS["search_performances"],
                               SearchInput, kopis.search_performances))
    registry.register(ToolSpec("get_performance_detail", "external", DESCRIPTIONS["get_performance_detail"],
                               DetailInput, kopis.get_performance_detail))
    registry.register(ToolSpec("search_nearby_places", "external", DESCRIPTIONS["search_nearby_places"],
                               NearbyInput, nearby.search_nearby_places))
    return registry
