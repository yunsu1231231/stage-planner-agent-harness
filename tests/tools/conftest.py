"""Tool 계약 테스트 공용 픽스처 — 녹화 응답 + FakeSession + 고정 시계."""
from __future__ import annotations

import json
from datetime import date

import pytest

from fakes import FakeResponse, FakeSession

TODAY = date(2026, 11, 22)               # 일요일. 녹화 시점과 맞춘다
KOPIS_KEY, KAKAO_KEY = "TESTKOPISKEY", "TESTKAKAOKEY"
UA = "ai-planner/0.1 (SSAFY AI core project)"

KOPIS_LIST = r"/openApi/restful/pblprfr$"
KOPIS_DETAIL = r"/openApi/restful/pblprfr/[^/]+$"
KOPIS_VENUE = r"/openApi/restful/prfplc/[^/]+$"
KAKAO_CATEGORY = r"dapi\.kakao\.com/v2/local/search/category\.json"


def kopis_xml(body: str, status: int = 200) -> FakeResponse:
    # 실제 KOPIS처럼 charset 없는 Content-Type → Tool이 utf-8 을 강제하지 않으면 한글이 깨진다
    return FakeResponse(status, body, content_type="application/xml")


def blocked() -> FakeResponse:
    return FakeResponse(400, "<HTML><BODY><H1>Request Blocked</H1></BODY></HTML>", content_type="text/html")


def kakao_json(body: str | dict, status: int = 200) -> FakeResponse:
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return FakeResponse(status, text, content_type="application/json;charset=UTF-8")


class SleepSpy:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleep_spy() -> SleepSpy:
    return SleepSpy()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def make_kopis(session, sleep_spy):
    from app.tools.kopis import KopisClient

    def make(api_key: str | None = KOPIS_KEY) -> KopisClient:
        return KopisClient(api_key=api_key, session=session, today=lambda: TODAY, sleep=sleep_spy)
    return make


@pytest.fixture
def make_registry(session, sleep_spy):
    from app.tools.factory import build_registry

    def make(kopis_key: str | None = KOPIS_KEY, kakao_key: str | None = KAKAO_KEY):
        return build_registry(kopis_key=kopis_key, kakao_key=kakao_key, session=session,
                              today=lambda: TODAY, sleep=sleep_spy)
    return make
