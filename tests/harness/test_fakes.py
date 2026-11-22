"""하네스 자체 검증 — 가짜 객체가 믿을 만해야 그 위의 테스트도 믿을 수 있다."""
from __future__ import annotations

import pytest
import requests
from pydantic import BaseModel

from conftest import NetworkBlocked
from fakes import FakeLLM, FakeResponse, FakeSession, UnexpectedHTTPCall, UnexpectedLLMCall


# ---------------------------------------------------------------- FakeLLM
class Intent(BaseModel):
    intent: str
    reason: str


def test_fake_llm_structured_output_validates_schema():
    llm = FakeLLM([{"intent": "chitchat", "reason": "인사"}])
    out = llm.with_structured_output(Intent).invoke("안녕")
    assert isinstance(out, Intent) and out.intent == "chitchat"
    assert llm.calls[0].kind == "structured"


def test_fake_llm_rejects_script_that_breaks_schema():
    llm = FakeLLM([{"intent": "chitchat"}])  # reason 누락
    with pytest.raises(Exception):
        llm.with_structured_output(Intent).invoke("안녕")


def test_fake_llm_tool_calls_and_unbound_tool_guard():
    llm = FakeLLM([[{"name": "search_performances", "args": {"start_date": "2026-11-28"}}],
                   [{"name": "not_registered"}]])
    msg = llm.bind_tools([{"name": "search_performances"}]).invoke("대학로 연극")
    assert msg.tool_calls[0]["name"] == "search_performances"
    with pytest.raises(AssertionError):
        llm.bind_tools([{"name": "search_performances"}]).invoke("x")


def test_fake_llm_fails_on_unscripted_call():
    llm = FakeLLM(["only one"])
    llm.invoke("1")
    with pytest.raises(UnexpectedLLMCall):
        llm.invoke("2")
    assert llm.call_count == 2


def test_fake_llm_can_inject_exception():
    llm = FakeLLM([TimeoutError("llm down")])
    with pytest.raises(TimeoutError):
        llm.invoke("x")


# ---------------------------------------------------------------- FakeSession
def test_fake_session_serves_fixture_and_records_call(fixture_text):
    s = FakeSession(headers={"User-Agent": "ai-planner/0.1"})
    s.add(r"/pblprfr$", FakeResponse(200, fixture_text("kopis_list.xml")))
    r = s.get("https://www.kopis.or.kr/openApi/restful/pblprfr", params={"service": "K", "rows": 5})
    assert r.ok and "<dbs>" in r.text
    assert s.calls[0].params["rows"] == 5 and s.calls[0].headers["User-Agent"] == "ai-planner/0.1"


def test_fake_session_reproduces_missing_charset_mojibake(fixture_text):
    r = FakeResponse(200, fixture_text("kopis_detail.xml"), content_type="application/xml")
    assert "공연" not in r.text and "시간" not in r.text      # requests 기본 동작: ISO-8859-1 → 깨짐
    r.encoding = "utf-8"
    assert "시간" in r.text                                     # Tool이 utf-8 을 강제해야 정상


def test_fake_session_sequence_then_repeat_last():
    blocked = FakeResponse(400, "<H1>Request Blocked</H1>", content_type="text/html")
    ok = FakeResponse(200, "<dbs/>")
    s = FakeSession().add(r"kopis", blocked, ok)
    assert [s.get("https://kopis").status_code for _ in range(3)] == [400, 200, 200]


def test_fake_session_injects_exception_and_rejects_unknown_url():
    s = FakeSession().add(r"kopis", requests.ConnectionError("reset"))
    with pytest.raises(requests.ConnectionError):
        s.get("https://kopis")
    with pytest.raises(UnexpectedHTTPCall):
        s.get("https://unknown.example")


# ---------------------------------------------------------------- 네트워크 차단
def test_offline_tests_cannot_reach_network():
    with pytest.raises((NetworkBlocked, requests.ConnectionError)):
        requests.get("https://www.kopis.or.kr", timeout=2)
